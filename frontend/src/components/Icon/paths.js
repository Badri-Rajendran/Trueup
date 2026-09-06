/**
 * Icon path data, 16x16 viewBox. Each entry is an array of `d` strings (one <path> per entry) --
 * no presentation attributes here; stroke/fill live in Icon.css so every glyph inherits the theme
 * via currentColor for free. Named export keeps this tree-shakeable; Icon.jsx looks these up by
 * string name for a small, reviewable API.
 */

export const ICON_PATHS = {
  'chevron-down': ['M4 6.5 8 10.5 12 6.5'],
  'chevron-up': ['M4 9.5 8 5.5 12 9.5'],
  'chevron-left': ['M9.5 4 5.5 8 9.5 12'],
  'chevron-right': ['M6.5 4 10.5 8 6.5 12'],
  'alert-triangle': ['M8 2.5 14.5 13.5h-13z', 'M8 6.5v3.2', 'M8 11.9v.1'],
  'alert-circle': ['M8 8m-6 0a6 6 0 1 0 12 0a6 6 0 1 0 -12 0', 'M8 5v3.5', 'M8 11v.1'],
  'check-circle': ['M8 8m-6 0a6 6 0 1 0 12 0a6 6 0 1 0 -12 0', 'M5.2 8.2 7.2 10 10.8 6'],
  'info-circle': ['M8 8m-6 0a6 6 0 1 0 12 0a6 6 0 1 0 -12 0', 'M8 7.2v3.3', 'M8 5v.1'],
  x: ['M4.5 4.5 11.5 11.5', 'M11.5 4.5 4.5 11.5'],
  search: ['M7 7m-4.2 0a4.2 4.2 0 1 0 8.4 0a4.2 4.2 0 1 0 -8.4 0', 'M10 10 13 13'],
  'external-link': ['M6.5 4.5H11.5V9.5', 'M11.5 4.5 5 11'],
  download: ['M8 2.5v7.2', 'M5 7 8 9.7 11 7', 'M3 12.5h10'],
  'arrow-left': ['M12.5 8h-9', 'M6.5 4 3 8l3.5 4'],
  send: ['M13.5 2.5 2.5 7.2l4.6 1.8 1.8 4.6z', 'M7.1 9 13.5 2.5'],
  refresh: [
    'M3.2 8a4.8 4.8 0 0 1 8-3.4l1 1',
    'M12.2 3v2.8h-2.8',
    'M12.8 8a4.8 4.8 0 0 1-8 3.4l-1-1',
    'M3.8 13v-2.8h2.8',
  ],
  menu: ['M2.5 4.5h11', 'M2.5 8h11', 'M2.5 11.5h11'],
}
