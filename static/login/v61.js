/* Login — SÓ o tema claro (v63, 17/11/2026: "remover de vez o tema dark").
   Script CLÁSSICO e síncrono, citado no <head> do login (server.py, _LOGIN_HTML): pinta a página clara
   antes do primeiro quadro. Não há mais chave de volta ao escuro: as preferências antigas (`jfn_v61=0`,
   `jfn_tema=escuro`) são apagadas aqui, como o painel já faz no <head> dele.
   Tudo o que cita mora em /static/login/ (a única pasta que o visitante sem sessão baixa). */
(function () {
  try { localStorage.removeItem('jfn_tema'); localStorage.removeItem('jfn_v61'); } catch (e) {}
  var h = document.documentElement; h.classList.add('v61');
  window.JFN_LOGIN_V61 = true;
  var l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/static/login/v61.css';
  document.head.appendChild(l);
  var m = document.querySelector('meta[name=color-scheme]'); if (m) m.content = 'light';
  var t = document.querySelector('meta[name=theme-color]'); if (t) t.content = '#F7FAFF';
})();
