"""v68 · CENAS 3D renderizadas (Blender 5.2, EEVEE, no it-campo) com os DADOS REAIS exportados por
`tools/v68_cenas_dados.py`. Nenhum texto queimado: rótulos e números ficam em código no painel.

  galaxia  voo pela galáxia de casos (/api/galaxia): esferas por nó (órgão, caso, fornecedor por faixa de
           score, sócio, processo SEI), arestas em fios finos, cada órgão um aglomerado em profundidade
           própria; a câmera entra de longe, atravessa a nuvem e para no único fornecedor CRÍTICO
           (score ≥ limiar do painel), que pulsa em âmbar (a cor de alerta da galáxia).
  mapa     os 92 municípios do RJ extrudados por √(valor contratado vigente atribuído) — a métrica da aba
           Mapa (/api/territorio/estado) —, acendendo numa varredura oeste→leste, câmera orbitando.

Linguagem v63: azul (#1D5BFF / #6FA8FF / #38D3FF) sobre branco-gelo, sem brilho de filtro; a profundidade
é uma névoa clara (a cor de cada material mistura ao fundo pela distância da câmera).

Uso: blender -b -P v68_blender_cenas.py -- <galaxia|mapa|alvos> <largura> <altura> <pasta_saida> [quadro_ini quadro_fim]
"""
import bpy
import bmesh
import json
import math
import sys
import os
import time
T0 = time.time()
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
CENA, W, H, SAIDA = argv[0], int(argv[1]), int(argv[2]), argv[3]
Q0, Q1 = (int(argv[4]), int(argv[5])) if len(argv) > 5 else (1, 960)
PASSO = int(argv[6]) if len(argv) > 6 else 1          # >1 = prova rápida (1 quadro a cada PASSO)
DADOS = os.path.dirname(os.path.abspath(__file__))
FPS, NQ = 60, 960                       # 16 s a 60 fps
FUNDO = (0.925, 0.955, 1.0)             # branco-gelo (linear ~ #F3F7FF depois da transformada)

def hexrgb(h):
    h = h.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((x + .055) / 1.055) ** 2.4 if x > .04045 else x / 12.92 for x in c)

COR = {k: hexrgb(v) for k, v in dict(tinta='#0B1B3A', cobalto='#1D5BFF', ceu='#6FA8FF', ciano='#38D3FF',
       gelo='#BFD3FF', alerta='#FFC400', orgao='#0B3D91', sei='#8FA4C8').items()}

# ---------------------------------------------------------------- cena base
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = FPS; sc.frame_start, sc.frame_end, sc.frame_step = Q0, Q1, PASSO
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
for eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
    try: sc.render.engine = eng; break
    except TypeError: print(f'[v68] motor {eng} indisponível nesta versão do Blender — tento o próximo', file=sys.stderr)
try: sc.eevee.taa_render_samples = 24
except AttributeError: print('[v68] eevee.taa_render_samples ausente — amostragem padrão do motor', file=sys.stderr)
sc.view_settings.view_transform = 'Standard'; sc.view_settings.look = 'None'
sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_depth = '8'
sc.render.image_settings.color_mode = 'RGB'      # RGBA quebra o RIFE ncnn (listras) — medido 18/11
sc.render.filepath = os.path.join(SAIDA, '')
sc.render.use_motion_blur = True
try: sc.render.motion_blur_shutter = .35
except AttributeError: print('[v68] motion_blur_shutter ausente — obturador padrão', file=sys.stderr)
w = bpy.data.worlds.new('fundo'); sc.world = w; w.use_nodes = True
bg = w.node_tree.nodes['Background']; bg.inputs[0].default_value = (*FUNDO, 1); bg.inputs[1].default_value = 1.0

def material(nome, cor, emis=0.0, alfa=1.0, perto=14.0, longe=110.0, rugo=.35):
    """Principled + névoa clara: mistura ao FUNDO pela distância à câmera (perspectiva atmosférica)."""
    m = bpy.data.materials.new(nome); m.use_nodes = True
    nt = m.node_tree; N = nt.nodes; L = nt.links
    for n in list(N): N.remove(n)
    out = N.new('ShaderNodeOutputMaterial')
    pr = N.new('ShaderNodeBsdfPrincipled')
    pr.inputs['Base Color'].default_value = (*cor, 1); pr.inputs['Roughness'].default_value = rugo
    pr.inputs['Emission Color'].default_value = (*cor, 1); pr.inputs['Emission Strength'].default_value = emis
    cam = N.new('ShaderNodeCameraData')
    mr = N.new('ShaderNodeMapRange'); mr.inputs[1].default_value = perto; mr.inputs[2].default_value = longe
    L.new(cam.outputs['View Distance'], mr.inputs[0])
    fog = N.new('ShaderNodeEmission'); fog.inputs[0].default_value = (*FUNDO, 1); fog.inputs[1].default_value = 1
    mix = N.new('ShaderNodeMixShader'); L.new(mr.outputs[0], mix.inputs[0]); L.new(pr.outputs[0], mix.inputs[1]); L.new(fog.outputs[0], mix.inputs[2])
    sh = mix
    if alfa < 1:
        tr = N.new('ShaderNodeBsdfTransparent'); m2 = N.new('ShaderNodeMixShader')
        m2.inputs[0].default_value = alfa; L.new(tr.outputs[0], m2.inputs[1]); L.new(mix.outputs[0], m2.inputs[2]); sh = m2
        try: m.surface_render_method = 'BLENDED'
        except AttributeError: m.blend_method = 'BLEND'
    L.new(sh.outputs[0], out.inputs[0])
    return m

def objeto(nome, bm, mat):
    me = bpy.data.meshes.new(nome); bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(nome, me); sc.collection.objects.link(ob); me.materials.append(mat)
    return ob

def camera(lente=35):
    cd = bpy.data.cameras.new('cam'); cd.lens = lente; cd.clip_end = 1000
    if H > W: cd.sensor_fit = 'VERTICAL'
    c = bpy.data.objects.new('cam', cd); sc.collection.objects.link(c); sc.camera = c
    return c

def chave(ob, prop, quadros_valores, interp='BEZIER'):
    for q, v in quadros_valores:
        setattr(ob, prop, v); ob.keyframe_insert(prop, frame=q)
    if ob.animation_data and ob.animation_data.action:
        try:
            for fc in ob.animation_data.action.fcurves:
                for k in fc.keyframe_points: k.interpolation = interp
        except AttributeError: print(f'[v68] fcurves indisponível ({ob.name}.{prop}) — interpolação padrão', file=sys.stderr)

def h01(i):                              # hash determinístico em [0,1)
    return ((i * 2654435761) % 4294967296) / 4294967296

def luz():
    s = bpy.data.lights.new('sol', 'SUN'); s.energy = 2.2; s.angle = .35
    o = bpy.data.objects.new('sol', s); sc.collection.objects.link(o); o.rotation_euler = (math.radians(40), 0, math.radians(30))

# ---------------------------------------------------------------- galáxia
def galaxia():
    g = json.load(open(os.path.join(DADOS, 'galaxia.json')))
    nos = g['nos']; E = 1 / 100
    pos = []
    for i, (x, y, t, cl, peso, crit) in enumerate(nos):
        zc = (h01(cl + 7) - .5) * 16                       # cada órgão (cluster) numa profundidade própria
        zj = (h01(i + 101) - .5) * (0.6 if t == 'orgao' else 2.4)
        pos.append(Vector((x * E, y * E, zc + zj)))
    def faixa(n):
        x, y, t, cl, peso, crit = n
        if crit: return 'critico'
        if t == 'cnpj': return 'cnpj_alto' if peso >= 25 else ('cnpj_med' if peso >= 10 else 'cnpj_baixo')
        return t
    est = {'orgao': (COR['orgao'], .5, lambda p: .16 + min(.22, p / 300)),
           'caso': (COR['cobalto'], 1.2, lambda p: .13 + min(.12, p / 300)),
           'cnpj_alto': (COR['cobalto'], .8, lambda p: .075),
           'cnpj_med': (COR['ceu'], .6, lambda p: .055),
           'cnpj_baixo': (COR['gelo'], .3, lambda p: .04),
           'socio': (COR['ciano'], .5, lambda p: .035),
           'sei': (COR['sei'], .2, lambda p: .04),
           'critico': (COR['alerta'], 3.0, lambda p: .16)}
    grupos = {}
    for i, n in enumerate(nos): grupos.setdefault(faixa(n), []).append(i)
    for gname, idx in grupos.items():
        cor, emis, raio = est[gname]
        bm = bmesh.new()
        for i in idx:
            r = raio(nos[i][4] or 1)
            bmesh.ops.create_icosphere(bm, subdivisions=3 if r > .1 else 2, radius=r,
                                       matrix=__import__('mathutils').Matrix.Translation(pos[i]))
        objeto('g_' + gname, bm, material('m_' + gname, cor, emis))
    # arestas: fios finos (curva poligonal por aresta)
    cu = bpy.data.curves.new('arestas', 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = .0035; cu.bevel_resolution = 0
    for a, b, tp in g['arestas']:
        sp = cu.splines.new('POLY'); sp.points.add(1)
        sp.points[0].co = (*pos[a], 1); sp.points[1].co = (*pos[b], 1)
    oc = bpy.data.objects.new('arestas', cu); sc.collection.objects.link(oc)
    cu.materials.append(material('m_aresta', COR['ceu'], .4, alfa=.2))
    luz()
    # alvo: o fornecedor crítico (score ≥ limiar do painel); sem nenhum → o caso de maior peso
    crit = grupos.get('critico') or sorted(grupos['caso'], key=lambda i: -nos[i][4])[:1]
    alvo = pos[crit[0]]
    centro = sum(pos, Vector()) / len(pos)
    # aura do crítico: casca âmbar translúcida que pulsa nos últimos 4 s
    bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=3, radius=.16)
    au = objeto('aura', bm, material('m_aura', COR['alerta'], 2.0, alfa=.22)); au.location = alvo
    chave(au, 'scale', [(1, Vector((1, 1, 1))), (NQ - 240, Vector((1, 1, 1)))] +
          [(NQ - 240 + k * 40 + 20, Vector((3.2, 3.2, 3.2)) if k % 2 == 0 else Vector((1.6, 1.6, 1.6))) for k in range(6)])
    # câmera: longe e alto → mergulha → atravessa o miolo → desacelera até o crítico
    cam = camera(32 if W >= H else 22)
    mira = bpy.data.objects.new('mira', None); sc.collection.objects.link(mira)
    tc = cam.constraints.new('TRACK_TO'); tc.target = mira; tc.track_axis = 'TRACK_NEGATIVE_Z'; tc.up_axis = 'UP_Y'
    d = (alvo - centro).normalized()
    lado = Vector((-d.y, d.x, 0)).normalized()
    p0 = centro + Vector((0, -34, 22))
    p1 = centro + Vector((-14, -18, 12))
    p2 = centro + lado * 6 + Vector((0, 0, 3))
    p3 = alvo + (centro - alvo).normalized() * 6.5 + Vector((0, 0, 1.6)) + lado * 1.5
    p4 = alvo + (centro - alvo).normalized() * 2.6 + Vector((0, 0, .7)) + lado * .6
    chave(cam, 'location', [(1, p0), (260, p1), (520, p2), (760, p3), (NQ, p4)])
    chave(mira, 'location', [(1, centro), (420, centro.lerp(alvo, .4)), (700, alvo), (NQ, alvo)])

# ---------------------------------------------------------------- mapa RJ
def mapa():
    m = json.load(open(os.path.join(DADOS, 'mapa.json')))
    E = 1 / 10                                           # 10 km = 1 unidade
    mun = m['municipios']; vmax = max(x['valor'] for x in mun) or 1
    # acendem numa varredura oeste → leste (centróide), de 1,5 s a 10 s
    cx = lambda x: sum(p[0] for a in x['aneis'] for p in a) / max(1, sum(len(a) for a in x['aneis']))
    ordem = sorted([x for x in mun if x['valor'] > 0], key=cx)
    ini = {x['cod']: 90 + int(k * (510 / max(1, len(ordem) - 1))) for k, x in enumerate(ordem)}
    base_mat = material('m_base', hexrgb('#CBDAF2'), 0, perto=60, longe=220)
    tudo = []
    for x in mun:
        h = .06 + (6.5 * math.sqrt(x['valor'] / vmax) if x['valor'] > 0 else 0)
        bm = bmesh.new()
        for anel in x['aneis']:
            vs = [bm.verts.new((px * E, py * E, 0)) for px, py in anel[:-1] if True]
            if len(vs) < 3: continue
            try: f = bm.faces.new(vs)
            except ValueError: continue
            r = bmesh.ops.extrude_face_region(bm, geom=[f])
            top = [v for v in r['geom'] if isinstance(v, bmesh.types.BMVert)]
            bmesh.ops.translate(bm, verts=top, vec=(0, 0, 1))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        if not bm.faces: bm.free(); continue
        q = x['valor'] / vmax
        cor = COR['cobalto'] if q > .25 else (COR['ceu'] if q > .03 else COR['gelo'])
        mat = base_mat if x['valor'] <= 0 else material('m_' + x['cod'], cor, 0, perto=60, longe=220)
        ob = objeto('mun_' + x['cod'], bm, mat)
        for p in ob.data.polygons: p.use_smooth = False
        tudo.append(ob)
        if x['valor'] <= 0:
            ob.scale = (1, 1, .06); continue
        q0 = ini[x['cod']]
        chave(ob, 'scale', [(1, Vector((1, 1, .02))), (q0, Vector((1, 1, .02))), (q0 + 70, Vector((1, 1, h * 1.08))), (q0 + 100, Vector((1, 1, h)))])
        # acende: a emissão sobe ao crescer e assenta num brilho baixo
        pr = mat.node_tree.nodes['Principled BSDF']
        es = pr.inputs['Emission Strength']
        for qq, v in [(1, 0), (q0, 0), (q0 + 60, .7), (q0 + 140, .12)]:
            es.default_value = v; es.keyframe_insert('default_value', frame=qq)
        pr.inputs['Emission Color'].default_value = (*COR['ciano'], 1)
    luz()
    xs = [v.co.x for o in tudo for v in o.data.vertices]; ys = [v.co.y for o in tudo for v in o.data.vertices]
    c = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, 0)); R = max(max(xs) - min(xs), max(ys) - min(ys))
    piv = bpy.data.objects.new('piv', None); sc.collection.objects.link(piv); piv.location = c
    cam = camera(40 if W >= H else 26); cam.parent = piv
    dist = R * (1.45 if W >= H else 2.3)
    cam.location = (0, -dist * .72, dist * .7)
    tc = cam.constraints.new('TRACK_TO'); tc.target = piv; tc.track_axis = 'TRACK_NEGATIVE_Z'; tc.up_axis = 'UP_Y'
    chave(piv, 'rotation_euler', [(1, Vector((0, 0, math.radians(-18)))), (NQ, Vector((0, 0, math.radians(28))))], 'LINEAR')

def alvos():
    """v70 · alvos de clique do relevo: monta a MESMA cena do mapa, vai ao último quadro renderizado (959, o
    que o vídeo congela) e projeta pela câmera cada face de cada município (bpy_extras.world_to_camera_view).
    Sai JSON em pixels do quadro W×H, com a distância à câmera para a ordem de oclusão; a união/recorte das
    faces vira contorno na vm1 (`tools/v70_mapa_alvos.py`). Não renderiza nada (só CPU)."""
    from bpy_extras.object_utils import world_to_camera_view
    mapa()
    sc.frame_set(959)
    dg = bpy.context.evaluated_depsgraph_get(); cam = sc.camera; pc = cam.matrix_world.translation
    out = []
    for ob in sc.objects:
        if not ob.name.startswith('mun_'): continue
        mw = ob.evaluated_get(dg).matrix_world; me = ob.data
        px = []
        for v in me.vertices:
            u = world_to_camera_view(sc, cam, mw @ v.co)
            px.append((round(u.x * W, 1), round((1 - u.y) * H, 1)))
        faces = [[px[i] for i in p.vertices] for p in me.polygons]
        cw = mw @ (sum((v.co for v in me.vertices), Vector()) / max(1, len(me.vertices)))
        out.append({'cod': ob.name[4:], 'dist': round((cw - pc).length, 3), 'faces': faces})
    os.makedirs(SAIDA, exist_ok=True)
    json.dump({'quadro': 959, 'w': W, 'h': H, 'municipios': out}, open(os.path.join(SAIDA, 'alvos_%dx%d.json' % (W, H)), 'w'), separators=(',', ':'))
    print('ALVOS-FIM', len(out), W, H, flush=True)
    sys.exit(0)

{'galaxia': galaxia, 'mapa': mapa, 'alvos': alvos}[CENA]()
if os.environ.get('V70_NITIDO'):          # v70 · quadro parado do relevo: câmera parada não pede rastro
    sc.render.use_motion_blur = False
    try: sc.eevee.taa_render_samples = 64
    except AttributeError: print('[v68] eevee.taa_render_samples ausente (V70_NITIDO) — amostragem padrão', file=sys.stderr)
os.makedirs(SAIDA, exist_ok=True)
print('CENA-MONTADA em %.0f s' % (time.time() - T0), flush=True)
bpy.ops.render.render(animation=True)
print('RENDER-FIM', CENA, W, H, Q0, Q1, 'em %.0f s' % (time.time() - T0))
