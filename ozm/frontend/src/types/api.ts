export interface SelectOption { value: string; label: string }
export interface ProfileShape { id: string; label: string; picture?: string }
export interface ProfileFamily { id: string; label: string; hard: number; shapes: ProfileShape[] }
export interface RollMark { id: string; shape: string; label: string; dims: Record<string, number> }
export interface MaterialRT { id: string; title: string; unit: string; q?: number; rate?: number }
export interface CalcConfig {
  taikorQ: number; ozmQ: number; ozbQ: number; steelDensity: number
  ozbByR: Record<string, number>
}
export interface DictsResponse {
  profiles: ProfileFamily[]
  roll: RollMark[]
  selects: Record<string, SelectOption[]>
  materials: MaterialRT[]
  config: CalcConfig
}

export interface HeatedSides { left: boolean; top: boolean; right: boolean; bottom: boolean }
export interface ElementInput {
  id?: string; title?: string; shape: string; rollId?: string
  dims?: Record<string, number>
  frType: string; htLevel: number; sides: HeatedSides
  lengthM: number; quantity: number; coat: string; method: string
  primer?: boolean; enamel?: boolean; decor?: boolean
  /** UI-only: OCR mark did not match roll dict. */
  profileMiss?: boolean
  /** UI-only: OCR construction (Балки / Ригели / …) for display title. */
  construction?: string
}
export interface GroupInput {
  id?: string; title?: string; quantity: number; elements: ElementInput[]
}
export interface BetonInput { areaM2: number; htLevel: number }
export interface CalcRequest {
  objectName: string; address: string; consent: boolean
  dominance?: string; frDurability: string
  groups: GroupInput[]; beton?: BetonInput | null
  materialPriceEditsCents?: Record<string, number>
}
export interface ElementResult {
  id: string; groupId: string; title: string; shape: string
  f: number; pi: number; dpr: number; delta: number; lining: number
  areaM2: number; volume: number; exclusion?: string
  coat: string; htLevel: number; lengthM: number; quantity: number
}
export interface MaterialLine {
  id: string; title: string; unit: string; quantity: number
  unitPriceCents: number; totalCents: number
  sourceElementId?: string
  sourceGroupId?: string
}
export interface CalcResponse {
  id?: string; inputs: CalcRequest
  elements: ElementResult[]; materials: MaterialLine[]
  totals: { materialsCents: number; grandCents: number }
  trace?: string[]
}
