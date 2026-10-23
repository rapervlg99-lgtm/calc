package export

import _ "embed"

// reportHeaderPNG — шапка спецификации: QR-код и логотип «ТЕХНОНИКОЛЬ ·
// Проектный сервис» одной картинкой (как в легаси-отчёте). Встраивается в файл,
// поэтому в контейнере не нужен ни том, ни доступ к файловой системе.
//
//go:embed assets/report_header.png
var reportHeaderPNG []byte
