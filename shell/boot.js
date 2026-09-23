// Independent of the renderer, provider, and main application. Never blocks input.
window.smilyReveal = () => document.querySelector('#boot')?.classList.add('revealed');
setTimeout(window.smilyReveal, 2200);
window.addEventListener('error', window.smilyReveal);
window.addEventListener('unhandledrejection', window.smilyReveal);
if (matchMedia('(prefers-reduced-motion: reduce)').matches) window.smilyReveal();
