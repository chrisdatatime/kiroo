// Páginas legais: só melhorias. Sem JS a página continua completa (os botões de imprimir ficam ocultos).
(function () {
  var d = document;
  var box = d.querySelector('.actions');
  if (box) {
    box.hidden = false;
    box.addEventListener('click', function (e) { if (e.target.closest('[data-print]')) window.print(); });
  }
  // sumário ativo ao rolar
  var links = {}, secs = [];
  d.querySelectorAll('.toc a[href^="#"]').forEach(function (a) {
    var s = d.getElementById(a.getAttribute('href').slice(1));
    if (s) { links[s.id] = a; secs.push(s); }
  });
  if (!secs.length || !('IntersectionObserver' in window)) return;
  var seen = {}, cur = null;
  function mark(id) {
    if (id === cur) return;
    if (cur) { links[cur].classList.remove('on'); links[cur].removeAttribute('aria-current'); }
    cur = id;
    if (id) { links[id].classList.add('on'); links[id].setAttribute('aria-current', 'location'); }
  }
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) { seen[e.target.id] = e.isIntersecting; });
    var hit = null;
    for (var i = 0; i < secs.length; i++) if (seen[secs[i].id]) { hit = secs[i].id; break; }
    if (hit) mark(hit);
  }, { rootMargin: '-15% 0px -70% 0px' });
  secs.forEach(function (s) { io.observe(s); });
})();
