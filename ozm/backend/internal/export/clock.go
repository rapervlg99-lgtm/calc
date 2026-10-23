package export

import (
	"time"
)

// yearNow — текущий год (для титульного листа и подписей в отчётах).
func yearNow() int {
	return time.Now().Year()
}
