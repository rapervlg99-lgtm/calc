package export

import _ "embed"

// Встроенные ресурсы отчётов: шапка (QR + логотип), отдельные логотип и QR для
// PDF, шрифт с кириллицей (DejaVu Sans, свободная лицензия — см.
// assets/DejaVu-LICENSE.txt). Всё в бинарнике: в контейнере не нужны ни тома,
// ни системные шрифты.

//go:embed assets/report_header.png
var reportHeaderPNG []byte

//go:embed assets/report_logo.png
var reportLogoPNG []byte

//go:embed assets/report_qr.png
var reportQRPNG []byte

//go:embed assets/DejaVuSans.ttf
var dejaVuSans []byte

//go:embed assets/DejaVuSans-Bold.ttf
var dejaVuSansBold []byte

// reportYear — текущий год для титульного листа (подменяется в тестах).
var reportYear = func() int { return yearNow() }
