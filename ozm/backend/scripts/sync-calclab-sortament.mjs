// Node.js 24+: use the actual CalcLab reference model, including its exclusions
// and grouping, rather than importing unclassified rows from the raw catalog.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';

const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = path.resolve(process.argv[2] || path.join(backend, '../../../calclab.pro'));
const write = process.argv.includes('--write');
const dataDir = path.join(source, 'frontend/public/data/fire-protection');
// Каталог в репозитории кальклаба переименован (09.10.2026): вместо
// profile_catalog_ivan_v028_stage2.json лежит один profile-catalog.json.
const catalogPath = [
  path.join(dataDir, 'profile_catalog_ivan_v028_stage2.json'),
  path.join(dataDir, 'profile-catalog.json'),
].find((p) => fs.existsSync(p));
if (!catalogPath) throw new Error('нет каталога профилей в ' + dataDir);
const indexPath = path.join(dataDir, 'gost-catalog-index.json');
const read = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const hash = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const { buildReferenceModel } = await import(pathToFileURL(path.join(source, 'frontend/src/lib/metal-profiles.ts')));
const catalog = read(catalogPath);
const model = buildReferenceModel(catalog, read(indexPath));
const rollPath = path.join(backend, 'dicts/roll.json');
const originalText = fs.readFileSync(rollPath, 'utf8');
const original = JSON.parse(originalText);
const originalById = new Map(original.map((r) => [r.id, r]));
const legacy = original.filter((r) => r.source !== 'calclab-metalloprokat');
const imported = [];
const groups = [];
let representedGeometry = 0;

function shapeFor(p) {
  const r = p.row;
  const fid = r.section_catalog_family_id;
  switch (p.shape) {
    case 'i_section': return [8, 9].includes(fid) ? 'I-beam_sl' : 'I-beam_sm';
    case 'channel': return [20, 21].includes(fid) ? 'channel_bent' : fid === 22 ? 'channel_sl' : 'channel_';
    case 'channel_unequal': return 'channel_unequal';
    case 'angle': return Math.abs(r.sec_h - r.sec_b) < 0.01 ? 'corner_e' : 'corner_ue';
    case 'tee': return 'brands_sm';
    case 'rhs_shs': return Math.abs(r.sec_h - r.sec_b) < 0.01 ? 'tube_sq' : 'profile_sm';
    case 'chs': return 'tube_sm';
    default: throw new Error(`Unsupported source shape ${p.shape}`);
  }
}

function dimensions(p) {
  const r = p.row;
  const d = { h: r.sec_h, b: r.sec_b, s: r.t_w, t: r.t_f, R: r.r_root || 0 };
  if (p.shape === 'channel_unequal') d.b1 = r.sec_b1;
  if (p.shape === 'rhs_shs' && Math.abs(r.sec_h - r.sec_b) < 0.01) d.A = r.sec_h;
  if (p.shape === 'chs') return { d: r.sec_h, h: r.t_w, s: r.t_w, t: r.t_w };
  if (p.shape === 'angle' && Math.abs(r.sec_h - r.sec_b) >= 0.01) d.B = r.sec_h;
  if (p.shape === 'tee') d.tr = r.t_f;
  for (const [key, value] of Object.entries(d)) {
    if (!Number.isFinite(value) || value < 0) throw new Error(`Invalid ${key} in ${p.id}`);
  }
  return d;
}

function normalized(r) {
  const d = r.dims;
  if (r.shape === 'tube_sm') return [d.d ?? d.h, d.s ?? d.h];
  const h = d.h ?? d.A ?? d.B ?? d.b;
  const b = d.b ?? d.A;
  const s = d.s ?? d.S ?? d.t;
  const t = d.t ?? d.S1 ?? d.S2 ?? s;
  return [h, b, s, t, d.b1 ?? 0];
}

for (const shape of model.shapes) for (const gost of shape.gosts) {
  let count = 0;
  for (const family of gost.families) for (const p of family.profiles) {
    const r = p.row;
    if (!(r.A_gross > 0 && r.mass_kg_per_m > 0)) throw new Error(`Missing area/mass in ${p.id}`);
    const converted = {
      id: `calclab:${p.id}`, shape: shapeFor(p), label: p.label, dims: dimensions(p),
      standard: gost.status === 'no_gost' ? 'Без ГОСТа — разрезка двутавров' : gost.code,
      standardLabel: gost.label, standardStatus: gost.status,
      familyLabel: family.label, source: 'calclab-metalloprokat', sourceRowId: p.id,
      areaMm2: r.A_gross, massPerMeter: r.mass_kg_per_m,
    };
    if (imported.some((r) => r.id === converted.id)) throw new Error(`Duplicate source ID ${p.id}`);
    const signature = normalized(converted);
    if (legacy.some((old) => old.shape === converted.shape && normalized(old).every((v, i) => Math.abs(v - signature[i]) <= 0.01))) representedGeometry++;
    imported.push(converted);
    count++;
  }
  groups.push({ shape: shape.shape, standard: gost.code, status: gost.status, profiles: count });
}
// Existing numeric IDs and dimensions remain intact, including custom legacy
// assortments not present in CalcLab. Standard-qualified IDs do not collide.
const merged = [...legacy, ...imported];
const report = {
  source: 'CalcLab /references/metalloprokat',
  catalogSha256: hash(catalogPath), gostIndexSha256: hash(indexPath),
  sourceCatalogRows: catalog.rows.length, referenceProfiles: model.totalProfiles,
  excludedOrHiddenRows: catalog.rows.length - model.totalProfiles,
  legacyProfilesPreserved: legacy.length,
  sourceProfilesWithLegacyGeometry: representedGeometry,
  sourceProfilesWithoutLegacyGeometry: imported.length - representedGeometry,
  addedStandardQualifiedProfiles: imported.filter((r) => !originalById.has(r.id)).length,
  totalRollProfiles: merged.length, groups,
};
if (write) {
  // Preserve legacy text (including its numeric formatting) when it is the
  // unchanged prefix; fall back to a value-preserving merge for custom layouts.
  const boundary = originalText.search(/,\r?\n  \{\r?\n    "id": "calclab:/);
  let prefix = boundary >= 0 ? originalText.slice(0, boundary) : originalText.trimEnd().slice(0, -1).trimEnd();
  try {
    if (JSON.stringify(JSON.parse(prefix + '\n]')) !== JSON.stringify(legacy)) prefix = JSON.stringify(legacy, null, 2).slice(0, -2);
  } catch { prefix = JSON.stringify(legacy, null, 2).slice(0, -2); }
  const additions = JSON.stringify(imported, null, 2).slice(2, -2);
  fs.writeFileSync(rollPath, prefix + ',\n' + additions + '\n]\n');
  const profilesPath = path.join(backend, 'dicts/profiles.json');
  const profiles = read(profilesPath);
  const channel = profiles.find((p) => p.id === 'channel');
  for (const entry of [
    { id: 'channel_bent', label: 'швеллер гнутый равнополочный', picture: 'channel_' },
    { id: 'channel_unequal', label: 'швеллер гнутый неравнополочный', picture: 'channel_unequal' },
  ]) if (!channel.shapes.some((p) => p.id === entry.id)) channel.shapes.push(entry);
  fs.writeFileSync(profilesPath, JSON.stringify(profiles, null, 2) + '\n');
  fs.writeFileSync(path.join(backend, '../docs/calclab-sortament-comparison.json'), JSON.stringify(report, null, 2) + '\n');
}
console.log(JSON.stringify(report, null, 2));
