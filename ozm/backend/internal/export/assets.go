package export

import "embed"

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

// reportLogoPlainPNG — логотип без плашки «Проектный сервис»: в образце
// (report.pdf) и в колонтитуле, и на титуле стоит именно он.
//
//go:embed assets/report_logo_plain.png
var reportLogoPlainPNG []byte

//go:embed assets/DejaVuSans.ttf
var dejaVuSans []byte

//go:embed assets/DejaVuSans-Bold.ttf
var dejaVuSansBold []byte

// Формулы набираются засечным шрифтом: переменные курсивом, числа прямым —
// как в легаси-документе.
//
//go:embed assets/DejaVuSerif.ttf
var dejaVuSerif []byte

//go:embed assets/DejaVuSerif-Italic.ttf
var dejaVuSerifItalic []byte

// appendixFS — сканы приложений (узлы устройства огнезащиты и технические
// листы). Лежат отдельными файлами: подпись в отчёте формируется по манифесту
// в pdf_appendix.go.
//
//go:embed assets/appendix/*
var appendixFS embed.FS

// reportYear — текущий год для титульного листа (подменяется в тестах).
var reportYear = func() int { return yearNow() }
