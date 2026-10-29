<?php
mysqli_report(MYSQLI_REPORT_OFF);

$host = "localhost";
$user = "root";
$pass = "";                 // XAMPP default is empty
$db   = "academic_assistant";

$conn = new mysqli($host, $user, $pass, $db);

if ($conn->connect_error) {
    http_response_code(500);
    header("Content-Type: application/json");
    echo json_encode(["success" => false, "error" => "Database connection failed"]);
    exit;
}

$conn->set_charset("utf8mb4");
