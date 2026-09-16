// Place each .ring[data-for] around its target, and each .callout[data-below]
// just under that target, so highlights stay correct when the layout shifts.
document.querySelectorAll('.ring[data-for]').forEach(function (ring) {
  var t = document.querySelector(ring.dataset.for); if (!t) return;
  var r = t.getBoundingClientRect(), pad = 6;
  ring.style.left = (r.left - pad) + 'px'; ring.style.top = (r.top - pad) + 'px';
  ring.style.width = (r.width + 2 * pad) + 'px'; ring.style.height = (r.height + 2 * pad) + 'px';
});
document.querySelectorAll('.callout[data-below]').forEach(function (c) {
  var t = document.querySelector(c.dataset.below); if (!t) return;
  var r = t.getBoundingClientRect();
  c.style.top = (r.bottom + 14) + 'px';
  var left = Math.min(r.left, document.body.clientWidth - c.offsetWidth - 16);
  c.style.left = Math.max(16, left) + 'px';
});
document.querySelectorAll('.callout[data-above]').forEach(function (c) {
  var t = document.querySelector(c.dataset.above); if (!t) return;
  var r = t.getBoundingClientRect();
  c.style.top = (r.top - c.offsetHeight - 14) + 'px';
  c.style.left = Math.max(16, Math.min(r.right - c.offsetWidth, document.body.clientWidth - c.offsetWidth - 16)) + 'px';
});
