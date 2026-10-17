<?php
// Proxy server-side a Yahoo Finance para datos intradía.
// /analisis-anomalia/proxy.php?symbol=^GSPC&interval=5m&from=YYYY-MM-DD&to=YYYY-MM-DD

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$symbol   = isset($_GET['symbol'])   ? $_GET['symbol']   : '';
$interval = isset($_GET['interval']) ? $_GET['interval'] : '5m';
$from     = isset($_GET['from'])     ? $_GET['from']     : '';
$to       = isset($_GET['to'])       ? $_GET['to']       : '';

$symbols_ok   = ['^GSPC', '^NDX', 'BTC-USD', 'GC=F'];
$intervals_ok = ['1m', '5m', '15m', '30m', '60m', '1d', '1wk', '1mo'];

if (!in_array($symbol, $symbols_ok, true)) {
    http_response_code(400);
    echo json_encode(['error' => 'Símbolo no permitido']);
    exit;
}
if (!in_array($interval, $intervals_ok, true)) {
    http_response_code(400);
    echo json_encode(['error' => 'Intervalo no permitido']);
    exit;
}
if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $from) || !preg_match('/^\d{4}-\d{2}-\d{2}$/', $to)) {
    http_response_code(400);
    echo json_encode(['error' => 'Fechas inválidas (YYYY-MM-DD)']);
    exit;
}

$p1 = strtotime($from . ' 00:00:00 UTC');
$p2 = strtotime($to   . ' 23:59:59 UTC');
if ($p1 === false || $p2 === false || $p2 <= $p1) {
    http_response_code(400);
    echo json_encode(['error' => 'Rango temporal inválido']);
    exit;
}

$url = 'https://query1.finance.yahoo.com/v8/finance/chart/' . rawurlencode($symbol)
     . '?period1=' . $p1 . '&period2=' . $p2 . '&interval=' . rawurlencode($interval);

$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => true,
    CURLOPT_TIMEOUT        => 20,
    CURLOPT_USERAGENT      => 'Mozilla/5.0',
]);
$body = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$err  = curl_error($ch);
curl_close($ch);

if ($body === false || $code >= 400) {
    http_response_code(502);
    echo json_encode(['error' => 'Upstream HTTP ' . $code, 'detail' => $err]);
    exit;
}

$json = json_decode($body, true);
if (!is_array($json) || !isset($json['chart']['result'][0])) {
    http_response_code(502);
    echo json_encode(['error' => 'Yahoo: respuesta inesperada', 'raw' => substr($body, 0, 200)]);
    exit;
}

$r = $json['chart']['result'][0];
$ts = isset($r['timestamp']) ? $r['timestamp'] : [];
$series = null;
if (isset($r['indicators']['adjclose'][0]['adjclose'])) {
    $series = $r['indicators']['adjclose'][0]['adjclose'];
} elseif (isset($r['indicators']['quote'][0]['close'])) {
    $series = $r['indicators']['quote'][0]['close'];
}
if (!is_array($series) || empty($series)) {
    http_response_code(502);
    echo json_encode(['error' => 'Sin serie de precios en la respuesta']);
    exit;
}

$prices = [];
$n = count($ts);
for ($i = 0; $i < $n; $i++) {
    if (!isset($series[$i]) || $series[$i] === null || !is_numeric($series[$i])) continue;
    $prices[] = [$ts[$i] * 1000, (float)$series[$i]];
}

if (count($prices) < 30) {
    http_response_code(502);
    echo json_encode(['error' => 'Sin datos suficientes en el rango', 'count' => count($prices)]);
    exit;
}

echo json_encode(['prices' => $prices, 'symbol' => $symbol, 'interval' => $interval]);
