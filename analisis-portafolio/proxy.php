<?php
// Proxy para datos diarios. Soporta todos los tickers del catálogo de portafolio.
// /analisis-portafolio/proxy.php?symbol=^GSPC&from=YYYY-MM-DD&to=YYYY-MM-DD

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$symbol = isset($_GET['symbol']) ? $_GET['symbol'] : '';
$from   = isset($_GET['from'])   ? $_GET['from']   : '';
$to     = isset($_GET['to'])     ? $_GET['to']     : '';

$whitelist = [
    '^NDX','GC=F','BTC-USD','^GSPC','URTH','^DJI','SI=F','BRK-B',
    'QDVE.DE','SMH','AIQ','VWO','EWJ','FXI',
    'TLT','IEF','SHY','AGG','LQD','HYG','EMB',
    'AMZN','AAPL','MSFT','NVDA','TSLA','GOOG','META',
    'TCEHY','TSM','NFLX','AZO','AVGO','JPM','UNH','LLY','V','MA',
    'WMT','ORCL','AMD','MU','ASML','XOM','INTC',
    'JNJ','KO','PG','CAT','HD','CVX','COST','PLTR','ARM','ABBV',
    'ETH-USD','SOL-USD','XRP-USD','BNB-USD','TRX-USD',
    'HG=F','PL=F','CL=F','NG=F','ZW=F','ZC=F'
];
if (!in_array($symbol, $whitelist, true)) {
    http_response_code(400);
    echo json_encode(['error' => 'Símbolo no permitido']);
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
     . '?period1=' . $p1 . '&period2=' . $p2 . '&interval=1d';

$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => true,
    CURLOPT_TIMEOUT        => 25,
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
    echo json_encode(['error' => 'Yahoo: respuesta inesperada']);
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

if (count($prices) < 50) {
    http_response_code(502);
    echo json_encode(['error' => 'Sin datos suficientes en el rango', 'count' => count($prices)]);
    exit;
}

echo json_encode(['prices' => $prices, 'symbol' => $symbol]);
