/* O10.7 · o GLOBO 3D (three-globe, vasturiano, MIT) — entrada do bundle tardio `static/js/globo.bundle.js`.
 *
 * Só é baixado quando a pessoa liga "Globo" na aba Orçamento por órgão (e nunca sob reduced-motion, modo sóbrio
 * ou celular: lá vale a imagem parada de `parado.js`). Não tem laço próprio: o three-globe nasce com a animação
 * PAUSADA (os FrameTicker internos dele seriam 3 laços de rAF a mais) e quem desenha é o laço único do painel
 * (o `laco` passado por quem chama), que também anda o traço dos arcos e o voo da câmera.
 *
 * Câmera: abre no globo inteiro e desce ao Brasil e ao RJ (auditoria O10.1 §8.2: com escopo só RJ, o globo é a
 * transição de entrada; o dado mora no Brasil/RJ). Cor: neutra; vermelho só para arco com parte paga a CNPJ com
 * achado Tier 1. Pago dentro do próprio município da UG = coluna no ponto (arco de comprimento zero). */
import * as THREE from 'three';
import ThreeGlobe from 'three-globe';
import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
import {feature} from 'topojson-client';
import paises from 'world-atlas/countries-110m.json';
import {coord, espessura, PONTO_INDISPONIVEL} from './dados.js';

const COR = {neutro: ['rgba(30,123,240,0.30)', 'rgba(10,99,209,0.95)'], t1: ['rgba(217,58,64,0.35)', 'rgba(190,42,49,1)'],
             tracejado: 'rgba(81,102,127,0.85)', sel: ['rgba(34,181,245,0.6)', 'rgba(20,112,230,1)']};
const VISTAS = {globo: {lat: -12, lng: -48, altitude: 2.6}, brasil: {lat: -16, lng: -47, altitude: 1.05},
                rj: {lat: -22.4, lng: -43.1, altitude: 0.42}};

export function criar(host, m, centros, {laco, aoApontar, voo = true} = {}) {
  const W = () => host.clientWidth || 640, H = () => host.clientHeight || 420;
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'high-performance'});
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(W(), H());
  renderer.domElement.className = 'gl-canvas';
  renderer.domElement.setAttribute('role', 'img');
  renderer.domElement.setAttribute('aria-label', `Globo: ${m.arcos.length} ligações de pagamento; a tabela equivalente está logo abaixo`);
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 2.2));
  const sol = new THREE.DirectionalLight(0xffffff, 1.4); sol.position.set(-200, 160, 300); scene.add(sol);
  const camera = new THREE.PerspectiveCamera(42, W() / H(), 0.5, 4000);

  const globo = new ThreeGlobe({animateIn: false})
    .showGraticules(true).showAtmosphere(true).atmosphereColor('#9CC8F7').atmosphereAltitude(0.14)
    .polygonsTransitionDuration(0).arcsTransitionDuration(0).pointsTransitionDuration(0);
  const mat = globo.globeMaterial(); mat.color = new THREE.Color('#EEF5FE'); mat.shininess = 6;
  const fc = feature(paises, paises.objects.countries).features;
  globo.polygonsData(fc).polygonAltitude(0.004).polygonSideColor(() => 'rgba(0,0,0,0)')
    .polygonCapColor(f => (f.properties.name === 'Brazil' ? 'rgba(173,206,245,0.95)' : 'rgba(214,228,246,0.9)'))
    .polygonStrokeColor(() => 'rgba(30,110,220,0.35)');
  scene.add(globo);
  globo.pauseAnimation();                       // nenhum rAF do three-globe: o laço é o do painel

  let sel = null;
  const corArco = a => (a.id === sel ? COR.sel : a.tracejado ? COR.tracejado : a.t1_centavos > 0 ? COR.t1 : COR.neutro);
  function dados(mm) {
    const arcs = [], pts = new Map();
    for (const a of mm.arcos) {
      const co = coord(a.o, centros), cd = a.tracejado ? PONTO_INDISPONIVEL : coord(a.d, centros);
      if (!co || !cd) continue;
      if (a.mesmo_lugar) { pts.set('c' + a.id, {lat: co[0], lng: co[1], arco: a, alt: 0.003 + 0.035 * Math.sqrt(a.centavos / mm.max_centavos), r: 0.09}); continue; }
      arcs.push({...a, sLat: co[0], sLng: co[1], eLat: cd[0], eLng: cd[1]});
      pts.set(a.o, {lat: co[0], lng: co[1], alt: 0.003, r: 0.10});
      if (!a.tracejado) pts.set(a.d, {lat: cd[0], lng: cd[1], alt: 0.003, r: 0.08});
    }
    globo.arcsData(arcs).arcStartLat('sLat').arcStartLng('sLng').arcEndLat('eLat').arcEndLng('eLng')
      .arcColor(corArco).arcAltitudeAutoScale(0.42)
      .arcStroke(a => espessura(a.centavos, mm.max_centavos, 0.04, 0.42))
      .arcDashLength(a => (a.tracejado ? 0.04 : a.origem_comprovada ? 0.55 : 0.08)).arcDashGap(a => (a.tracejado ? 0.035 : a.origem_comprovada ? 0.12 : 0.05))
      .arcDashAnimateTime(a => (a.tracejado || !voo ? 0 : 2600));
    globo.pointsData([...pts.values()]).pointLat('lat').pointLng('lng').pointAltitude('alt').pointRadius('r')
      .pointColor(p => (p.arco ? (p.arco.id === sel ? COR.sel[1] : p.arco.t1_centavos > 0 ? COR.t1[1] : '#1470E6') : '#0B1B33'));
  }
  dados(m);

  const controles = new OrbitControls(camera, renderer.domElement);
  controles.enableDamping = false; controles.enablePan = false;
  controles.minDistance = 101.5; controles.maxDistance = 600; controles.rotateSpeed = 0.45; controles.zoomSpeed = 0.8;

  const pos = v => { const c = globo.getCoords(v.lat, v.lng, v.altitude); return new THREE.Vector3(c.x, c.y, c.z); };
  camera.position.copy(pos(voo ? VISTAS.globo : VISTAS.brasil)); camera.lookAt(0, 0, 0);
  let tween = null;
  function voar(nome, ms = 1800) {
    const de = camera.position.clone(), para = pos(VISTAS[nome] || VISTAS.brasil);
    if (!voo || ms <= 0) { camera.position.copy(para); camera.lookAt(0, 0, 0); return; }
    tween = {de, para, t0: performance.now(), ms};
  }
  if (voo) setTimeout(() => voar('brasil', 2200), 350);

  // hover/clique: raio contra os objetos do three-globe (cada um carrega o seu `__data`)
  const raio = new THREE.Raycaster(), ptr = new THREE.Vector2();
  let apontar = null;
  const achar = ev => {
    const r = renderer.domElement.getBoundingClientRect();
    ptr.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    raio.setFromCamera(ptr, camera);
    for (const hit of raio.intersectObjects(globo.children, true)) {
      let o = hit.object;
      while (o && !(o.__data && (o.__globeObjType === 'arc' || o.__globeObjType === 'point'))) o = o.parent;
      if (o) { const d = o.__data; const a = d.arco || (d.rotulo ? d : null); if (a) return a; }
    }
    return null;
  };
  renderer.domElement.addEventListener('pointermove', ev => { apontar = ev; });
  renderer.domElement.addEventListener('pointerleave', () => { apontar = null; aoApontar && aoApontar(null); });

  let ativo = true, rodando = true, ultApontado;
  const passo = (t, dt) => {
    if (!ativo) return false;
    if (!rodando) return true;
    if (tween) {
      const k = Math.min(1, (performance.now() - tween.t0) / tween.ms), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      camera.position.lerpVectors(tween.de, tween.para, e).setLength(tween.de.length() + (tween.para.length() - tween.de.length()) * e);
      camera.lookAt(0, 0, 0);
      if (k >= 1) tween = null;
    }
    if (voo) {                                        // o traço dos arcos anda no laço do painel
      globo.traverse(o => {
        if (o.__dashAnimateStep && o.material && o.material.uniforms && o.material.uniforms.dashTranslate) {
          o.material.uniforms.dashTranslate.value = (o.material.uniforms.dashTranslate.value + o.__dashAnimateStep * dt) % 1e9;
        }
      });
    }
    if (apontar) { const a = achar(apontar); apontar = null; if (a !== ultApontado) { ultApontado = a; aoApontar && aoApontar(a); } }
    globo.setPointOfView(camera);
    renderer.render(scene, camera);
    return true;
  };
  const desligar = laco(passo);
  const ro = new ResizeObserver(() => { renderer.setSize(W(), H()); camera.aspect = W() / H(); camera.updateProjectionMatrix(); });
  ro.observe(host);

  return {
    atualizar(mm) { m = mm; dados(mm); },
    selecionar(id) { sel = id; dados(m); },
    voar,
    pausar(v) { rodando = !v; },
    quadro() { passo(performance.now(), 0); },
    sair() {
      ativo = false; desligar(); ro.disconnect(); controles.dispose();
      globo._destructor && globo._destructor();
      renderer.dispose(); renderer.forceContextLoss && renderer.forceContextLoss(); renderer.domElement.remove();
    },
  };
}
