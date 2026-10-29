<?php
header("Access-Control-Allow-Origin: *");
header("Access-Control-Allow-Methods: POST, OPTIONS");
header("Access-Control-Allow-Headers: Content-Type");
header("Content-Type: application/json; charset=utf-8");
if ($_SERVER["REQUEST_METHOD"] === "OPTIONS") { http_response_code(204); exit; }

require "db_connect.php";

if (isset($_POST["id"])) {                       // one paper (with full text)
    $id = (int)$_POST["id"];
    $stmt = $conn->prepare("SELECT id, category, title, content FROM documents WHERE id = ?");
    $stmt->bind_param("i", $id);
    $stmt->execute();
    $row = $stmt->get_result()->fetch_assoc();
    echo json_encode(["success" => (bool)$row, "paper" => $row], JSON_UNESCAPED_UNICODE);
} else {                                         // list of all papers (no text)
    $res = $conn->query("SELECT id, category, title FROM documents ORDER BY title");
    $rows = [];
    while ($r = $res->fetch_assoc()) { $rows[] = $r; }
    echo json_encode(["success" => true, "papers" => $rows], JSON_UNESCAPED_UNICODE);
}
$conn->close();
