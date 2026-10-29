<?php
// ---- CORS ----
header("Access-Control-Allow-Origin: *");
header("Access-Control-Allow-Methods: POST, OPTIONS");
header("Access-Control-Allow-Headers: Content-Type");
header("Content-Type: application/json; charset=utf-8");

if ($_SERVER["REQUEST_METHOD"] === "OPTIONS") { http_response_code(204); exit; }
if ($_SERVER["REQUEST_METHOD"] !== "POST") {
    http_response_code(405);
    echo json_encode(["success" => false, "error" => "Use POST"]);
    exit;
}

require "db_connect.php";

// ---- Read query (form-data OR JSON body) ----
$query = $_POST["query"] ?? null;
if ($query === null) {
    $json = json_decode(file_get_contents("php://input"), true);
    $query = $json["query"] ?? "";
}
$query = trim($query);
$limit = isset($_POST["limit"]) ? max(1, min(15, (int)$_POST["limit"])) : 5;

if ($query === "") {
    http_response_code(400);
    echo json_encode(["success" => false, "error" => "Empty query"]);
    exit;
}

// ---- Turn the question into keywords ----
$stop = ["when","what","where","who","how","is","are","the","a","an","of","for","to","in",
         "on","at","and","or","me","my","please","tell","give","show","do","does","can",
         "i","about","there","any","will","be","this","that","with","from","it",
         "important","questions","question","suggest","expected","repeated","frequently",
         "paper","papers","previous","latest","old",
         "asked","most","likely","exam","which","so","also"];

$words = preg_split('/[^\p{L}\p{N}]+/u', mb_strtolower($query), -1, PREG_SPLIT_NO_EMPTY);
$words = array_values(array_unique(array_diff($words, $stop)));
$words = array_slice($words, 0, 8);

if (count($words) === 0) {
    echo json_encode(["success" => true, "count" => 0, "results" => []]);
    exit;
}

// ---- Build prepared statement: score = weighted keyword matches ----
$scoreParts = [];
$whereParts = [];
$params = [];

foreach ($words as $w) {
    $like = "%" . addcslashes($w, "%_\\") . "%";
    // title match counts 4, keywords 2, content 1  -> the paper named like the query ranks first
    $scoreParts[] = "((title LIKE ?) * 4 + (keywords LIKE ?) * 2 + (content LIKE ?))";
    $whereParts[] = "title LIKE ? OR content LIKE ? OR keywords LIKE ?";
    array_push($params, $like, $like, $like);   // same pattern three times, so order does not matter
}

$sql = "SELECT id, category, title, content, keywords, (" . implode(" + ", $scoreParts) . ") AS score
        FROM documents
        WHERE " . implode(" OR ", $whereParts) . "
        ORDER BY score DESC
        LIMIT " . $limit;

$allParams = array_merge($params, $params);   // once for score, once for WHERE
$types = str_repeat("s", count($allParams));

$stmt = $conn->prepare($sql);
if (!$stmt) {
    http_response_code(500);
    echo json_encode(["success" => false, "error" => "Query preparation failed"]);
    exit;
}
$stmt->bind_param($types, ...$allParams);
$stmt->execute();
$res = $stmt->get_result();

$rows = [];
while ($r = $res->fetch_assoc()) { $rows[] = $r; }

echo json_encode([
    "success"  => true,
    "query"    => $query,
    "keywords" => $words,
    "count"    => count($rows),
    "results"  => $rows
], JSON_UNESCAPED_UNICODE);

$stmt->close();
$conn->close();
