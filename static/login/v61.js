/* v61 TRON CLARO — a porta de entrada no tema claro.
   Script CLÁSSICO e síncrono, citado no <head> do login (server.py, _LOGIN_HTML): decide o tema antes
   de a página pintar. Mesma regra do painel: `jfn_v61` ligada e `jfn_tema` ≠ escuro → classe `v61`.
   Tudo o que cita mora em /static/login/ (a única pasta que o visitante sem sessão baixa). */
(function () {
  var PADRAO = '1';   /* fase 11 do brief: vira '1' junto com window.JFN_V61_DEFAULT do painel */
  try {
    var q = new URLSearchParams(location.search).get('v61');
    if (q === '1' || q === '0') localStorage.setItem('jfn_v61', q);
    var on = localStorage.getItem('jfn_v61'); if (on === null) on = PADRAO;
    if (on !== '1' || localStorage.getItem('jfn_tema') === 'escuro') return;
  } catch (e) { return; }
  var h = document.documentElement; h.classList.add('v61');
  window.JFN_LOGIN_V61 = true;
  var l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/static/login/v61.css';
  document.head.appendChild(l);
  var m = document.querySelector('meta[name=color-scheme]'); if (m) m.content = 'light';
  var t = document.querySelector('meta[name=theme-color]'); if (t) t.content = '#F3F8FE';
})();
