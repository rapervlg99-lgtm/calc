import { h, type VNode } from 'vue';

function glassCard(
  pos: Record<string, string>,
  children: VNode[],
  animName: string,
  delay: number,
  ambient: boolean,
): VNode {
  return h(
    'div',
    {
      class: 'gsh-scene__card',
      style: {
        ...pos,
        animation: ambient ? `${animName} ${5 + delay}s ease-in-out ${delay}s infinite` : 'none',
      },
    },
    children,
  );
}

function iconUse(name: string, size = 20): VNode {
  return h(
    'svg',
    { viewBox: '0 0 24 24', fill: 'none', style: { width: `${size}px`, height: `${size}px` } },
    [h('use', { href: `#icon--${name}` })],
  );
}

export function buildGshTitleScene(ambientMotion: boolean): VNode {
  const main = glassCard(
    { top: '46px', right: '2px', width: '236px' },
    [
      h('div', { class: 'gsh-scene__mono' }, 'Подобрано'),
      h('div', { class: 'gsh-scene__row' }, [
        h('span', { class: 'gsh-scene__icon' }, [iconUse('protect')]),
        h('div', {}, [
          h('div', { class: 'gsh-scene__title' }, 'EM-260/20'),
          h('div', { class: 'gsh-scene__sub' }, 'ЕКН 499887'),
        ]),
      ]),
      h(
        'div',
        { class: 'gsh-scene__chips' },
        [
          ['Шов', 'ДШ'],
          ['Место', 'наруж'],
          ['Раскр.', '20-30'],
        ].map(([label, val]) =>
          h('div', { class: 'gsh-scene__chip' }, [
            h('div', { class: 'gsh-scene__chip-label' }, label),
            h('div', { class: 'gsh-scene__chip-val' }, val),
          ]),
        ),
      ),
    ],
    'floaty',
    0.2,
    ambientMotion,
  );

  const steps = glassCard(
    { top: '2px', left: '0' },
    [
      h('div', { class: 'gsh-scene__steps' }, [
        ...[1, 2, 3, 4].flatMap((n, i) => [
          h('span', { class: ['gsh-scene__step', i === 0 ? 'gsh-scene__step--active' : ''] }, String(n)),
          ...(i < 3 ? [h('span', { class: 'gsh-scene__step-line' })] : []),
        ]),
      ]),
    ],
    'floaty2',
    0.6,
    ambientMotion,
  );

  const chip = glassCard(
    { bottom: '10px', left: '22px' },
    [
      h('div', { class: 'gsh-scene__row' }, [
        h('span', { class: 'gsh-scene__icon gsh-scene__icon--dark' }, [iconUse('protect', 18)]),
        h('div', {}, [
          h('div', { class: 'gsh-scene__mono' }, 'ПВХ · шов бетона'),
          h('div', { class: 'gsh-scene__thermal' }, 'Гидрошпонка'),
        ]),
      ]),
    ],
    'floaty3',
    1.0,
    ambientMotion,
  );

  const dots = [
    [12, 44, 6, '#e11b11', 0],
    [402, 22, 5, '#9ca3b6', 0.6],
    [388, 252, 7, '#e11b11', 1.1],
    [32, 204, 5, '#c8ccd6', 0.3],
    [204, 8, 4, '#e11b11', 0.9],
  ].map(([left, top, size, color, delay], i) =>
    h('span', {
      class: 'gsh-scene__dot',
      style: {
        left: `${left}px`,
        top: `${top}px`,
        width: `${size}px`,
        height: `${size}px`,
        background: color as string,
        boxShadow: color === '#e11b11' ? '0 0 10px rgba(225,27,17,.6)' : 'none',
        animation: ambientMotion
          ? `twinkle ${3 + (i % 3)}s ease-in-out ${delay}s infinite`
          : 'none',
      },
    }),
  );

  return h('div', { class: 'gsh-scene' }, [...dots, steps, main, chip]);
}
