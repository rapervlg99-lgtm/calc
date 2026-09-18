import { type GshRow, gshProductNodesSrc, stripHtml } from '@/data/gsh';
import { ensurePdfMake } from '@/lib/pdfmake-loader';

export interface GshPdfParams {
  purpose: string;
  seamType: string;
  location: string;
  clarification: string;
  stage: string;
}

const RED = '#e11b11';
const LINK_COLOR = '#1a56cc';
const BORDER = '#cccccc';

/**
 * PDF-аннотации принимают только ASCII-URI: кириллица в query nav.tn.ru
 * должна быть закодирована, иначе ссылка в ридере не открывается.
 * new URL(...).href кодирует не-ASCII и не трогает уже закодированные %xx.
 */
function pdfSafeUrl(url: string): string {
  try {
    return new URL(url, window.location.origin).href;
  } catch {
    return url;
  }
}

function docLinks(row: GshRow): unknown {
  const links: unknown[] = [];
  if (row.k) {
    links.push({
      text: 'Техлист',
      link: pdfSafeUrl(row.k),
      color: LINK_COLOR,
      decoration: 'underline',
    });
  }
  if (row.nodes) {
    links.push({
      text: 'Примеры узлов',
      link: pdfSafeUrl(gshProductNodesSrc(row.h)),
      color: LINK_COLOR,
      decoration: 'underline',
      margin: [0, links.length ? 3 : 0, 0, 0],
    });
  }
  if (!links.length) return { text: '—' };
  return { stack: links };
}

function tableLayout() {
  return {
    hLineWidth: () => 0.5,
    vLineWidth: () => 0.5,
    hLineColor: () => BORDER,
    vLineColor: () => BORDER,
    paddingTop: () => 5,
    paddingBottom: () => 5,
    paddingLeft: () => 6,
    paddingRight: () => 6,
  };
}

function buildDocDefinition(params: GshPdfParams, results: GshRow[]) {
  const reportDate = new Date().toLocaleDateString('ru-RU');

  const paramsBody = [
    ['Назначение', params.purpose],
    ['Тип шва', params.seamType],
    ['Расположение', params.location],
    ['Уточнение', params.clarification],
    ['Стадия строительства', params.stage],
  ].map(([label, value]) => [
    { text: label, bold: true, fillColor: '#f9f9fa' },
    { text: value || '—' },
  ]);

  const resultsHeader = ['ЕКН', 'Наименование', 'Расход на п.м', 'Особенности применения', 'Документы'].map(
    (text) => ({ text, bold: true, fillColor: '#f0f4f8' }),
  );

  const resultsBody = results.map((row) => [
    { text: row.g, bold: true },
    { text: row.h },
    { text: stripHtml(row.i) },
    { text: row.j && row.j !== '—' ? stripHtml(row.j) : '—' },
    docLinks(row),
  ]);

  return {
    info: { title: 'Отчет конфигуратора гидрошпонок' },
    pageSize: 'A4',
    pageMargins: [40, 40, 40, 50],
    defaultStyle: {
      font: 'Roboto',
      fontSize: 9,
      lineHeight: 1.25,
      color: '#1e2228',
    },
    content: [
      {
        columns: [
          {
            text: [
              { text: 'CalcLab', fontSize: 18, bold: true },
              { text: '.pro', fontSize: 18, bold: true, color: RED },
            ],
            width: 'auto',
          },
          {
            text: 'Отчёт по подбору гидрошпонки ТЕХНОНИКОЛЬ',
            alignment: 'right',
            fontSize: 11,
            color: '#667387',
            margin: [0, 6, 0, 0],
          },
        ],
        margin: [0, 0, 0, 10],
      },
      {
        canvas: [{ type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 2, lineColor: RED }],
        margin: [0, 0, 0, 18],
      },
      { text: 'Исходные данные подбора', fontSize: 13, bold: true, margin: [0, 0, 0, 8] },
      {
        table: { widths: ['38%', '*'], body: paramsBody },
        layout: tableLayout(),
        margin: [0, 0, 0, 18],
      },
      {
        text: `Результаты подбора · найдено ${results.length}`,
        fontSize: 13,
        bold: true,
        margin: [0, 0, 0, 8],
      },
      {
        table: {
          headerRows: 1,
          widths: ['12%', '24%', '12%', '*', '16%'],
          body: [resultsHeader, ...resultsBody],
        },
        layout: tableLayout(),
      },
      {
        text: `ТЕХНОНИКОЛЬ · CalcLab.pro · значения расхода ориентировочные · ${reportDate}`,
        alignment: 'center',
        fontSize: 8,
        color: '#9ca3b6',
        margin: [0, 24, 0, 0],
      },
    ],
  };
}

export async function downloadGshPdf(params: GshPdfParams, results: GshRow[]): Promise<void> {
  await ensurePdfMake();
  const docDefinition = buildDocDefinition(params, results);
  window.pdfMake!.createPdf(docDefinition).download('Отчет конфигуратора гидрошпонок.pdf');
}
