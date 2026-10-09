const main = document.querySelector('main');
const viewer = document.querySelector('.lightbox');
const viewerImage = document.getElementById('viewer-image');
const viewerStage = document.querySelector('.viewer-stage');
const closeButton = document.getElementById('viewer-close');
const zoomButton = document.getElementById('viewer-zoom');
let assets = lightboxAssets;
let imageIndex = 0;
let lastFocus = null;
let scrollPending = false;

function updateActiveCase() {
  const sections = [...main.querySelectorAll('.case')];
  const atBottom = scrollY > 0 && scrollY + innerHeight >= document.documentElement.scrollHeight - 2;
  let section = sections.filter(item => item.getBoundingClientRect().top <= 110).at(-1) || sections[0];
  if (atBottom) section = sections.at(-1);
  main.querySelectorAll('.case-nav a').forEach(link => {
    const active = section && link.getAttribute('href') === '#' + section.id;
    link.classList.toggle('active', Boolean(active));
    if (active) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
  scrollPending = false;
}

function scheduleActiveCase() {
  if (scrollPending) return;
  scrollPending = true;
  requestAnimationFrame(updateActiveCase);
}

window.addEventListener('scroll', scheduleActiveCase, {passive: true});
window.addEventListener('resize', scheduleActiveCase);

function showImage(index, trigger) {
  if (!assets.length) return;
  if (trigger) lastFocus = trigger;
  imageIndex = (index + assets.length) % assets.length;
  const wasOpen = viewer.classList.contains('open');
  const asset = assets[imageIndex];
  viewerImage.src = asset.src;
  viewerImage.alt = asset.label;
  document.getElementById('viewer-title').textContent = asset.label;
  document.getElementById('viewer-caption').textContent = asset.note;
  document.getElementById('viewer-position').textContent = `${asset.caseId} · ${imageIndex + 1} / ${assets.length}`;
  document.getElementById('viewer-meta').textContent = asset.meta;
  viewerStage.classList.remove('zoomed');
  zoomButton.textContent = '原始尺寸';
  zoomButton.setAttribute('aria-pressed', 'false');
  viewer.classList.add('open');
  viewer.setAttribute('aria-hidden', 'false');
  main.inert = true;
  document.body.style.overflow = 'hidden';
  viewerStage.scrollTo(0, 0);
  if (!wasOpen) closeButton.focus();
}

function closeViewer() {
  viewer.classList.remove('open');
  viewer.setAttribute('aria-hidden', 'true');
  viewerImage.removeAttribute('src');
  main.inert = false;
  document.body.style.overflow = '';
  if (lastFocus?.isConnected) lastFocus.focus();
}

function bindReport() {
  main.querySelectorAll('[data-image]').forEach(button => {
    button.addEventListener('click', () => showImage(Number(button.dataset.image), button));
  });
  const selector = document.getElementById('report-round');
  selector?.addEventListener('change', () => {
    const view = roundViews[selector.value];
    if (!view) return;
    closeViewer();
    main.querySelectorAll('video,audio').forEach(media => media.pause());
    main.innerHTML = view.html;
    assets = view.assets;
    document.title = view.title;
    lastFocus = null;
    bindReport();
    window.scrollTo({top: 0, behavior: 'instant'});
    document.getElementById('report-round').focus();
  });
  selector?.addEventListener('keydown', event => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const last = selector.options.length - 1;
    const indices = {ArrowDown: Math.min(last, selector.selectedIndex + 1), ArrowUp: Math.max(0, selector.selectedIndex - 1), Home: 0, End: last};
    if (!Object.prototype.hasOwnProperty.call(indices, event.key)) return;
    event.preventDefault();
    if (selector.selectedIndex === indices[event.key]) return;
    selector.selectedIndex = indices[event.key];
    selector.dispatchEvent(new Event('change', {bubbles: true}));
  });
  main.querySelectorAll('.evidence img').forEach(img => {
    const classify = () => {
      if (!img.naturalWidth || !img.naturalHeight) return;
      const portrait = img.naturalHeight / img.naturalWidth > 1.25;
      const figure = img.closest('figure');
      figure.classList.toggle('portrait', portrait);
      figure.classList.toggle('wide-asset', !portrait);
      figure.classList.toggle('tiny-asset', !portrait && img.naturalWidth < 400);
      const gallery = img.closest('.gallery');
      const media = [...gallery.querySelectorAll('img,video,audio')];
      const allPortrait = media.every(item => item.tagName === 'IMG' && item.naturalWidth && item.naturalHeight / item.naturalWidth > 1.25);
      gallery.classList.toggle('wide', !allPortrait);
    };
    img.addEventListener('load', classify, {once: true});
    if (img.complete) classify();
  });
  scheduleActiveCase();
}

closeButton.addEventListener('click', closeViewer);
document.getElementById('viewer-prev').addEventListener('click', () => showImage(imageIndex - 1));
document.getElementById('viewer-next').addEventListener('click', () => showImage(imageIndex + 1));
zoomButton.addEventListener('click', () => {
  const zoomed = viewerStage.classList.toggle('zoomed');
  zoomButton.textContent = zoomed ? '适应窗口' : '原始尺寸';
  zoomButton.setAttribute('aria-pressed', String(zoomed));
});
viewerStage.addEventListener('click', event => { if (event.target === viewerStage) closeViewer(); });
document.addEventListener('keydown', event => {
  if (!viewer.classList.contains('open')) return;
  if (event.key === 'Escape') closeViewer();
  if (event.key === 'ArrowLeft') { event.preventDefault(); showImage(imageIndex - 1); }
  if (event.key === 'ArrowRight') { event.preventDefault(); showImage(imageIndex + 1); }
  if (event.key === 'Tab') {
    const controls = [...viewer.querySelectorAll('button,[tabindex="0"]')];
    const index = controls.indexOf(document.activeElement);
    if (event.shiftKey && index <= 0) { event.preventDefault(); controls.at(-1).focus(); }
    else if (!event.shiftKey && index === controls.length - 1) { event.preventDefault(); controls[0].focus(); }
  }
});
bindReport();
