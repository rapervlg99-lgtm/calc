# Calc rules summary

Подробности реализации: `backend/internal/calc`. Oracle: legacy `ars-A3.xsl`.

## δпр

\[
\delta_{пр} = F / \Pi \quad (\mathrm{mm})
\]

F — площадь сечения (мм²) по семье профиля; Π — обогреваемый периметр (мм) с учётом сторон нагрева.

## ОЗМ (coat=1)

1. Lookup `t500`: base δпр → minute = round(a·(δпр−base)+b) → минимальная толщина плиты с minute ≥ R.
2. lining: 1 короб / 2 контур (тавр/уголок) / 3 round (труба sm + контур).
3. \( V = S_v · (\delta/1000) · q \), \( q = 1.25 \).
4. Сопутствующие: клей 1.2 кг/м², штукатурка 3.2 кг/м² (по Lh), анкеры 7 шт/м².

## TAIKOR (coat 2/3/4)

Lookup `x500` coat[index] R[min=R] row по δпр.  
\( m = (\Pi/1000)·L · rate · taikor_q \), \( taikor_q = 1.43 \).  
Coat4 может добавить Extra (`heat`).

## АКЗ (coat 1.5)

Exclusion: ручной ввод.

## Бетон / ОЗБ

R240 → δ=40 мм (ОЗБ 110); R180 → δ=50 (ОЗБ 80); \( V = S·δ/1000·1.03 \).

## Golden

`backend/internal/calc/testdata/golden/*.json` — расширять матрицей семья×coat×method×R.
