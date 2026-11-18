"""v69 · ABERTURA CINE — animação de marca renderizada no Blender (5.2 LTS, EEVEE, no it-campo).

Substitui a tentativa do v68 (LTX-Video, que não obedecia roteiro) por uma cena 100 % controlada por código:

  0,0–1,4 s  convergência   ~260 fitas de luz finas entram pelas bordas e se enrolam em espiral até o anel
                            ("cometas": o trecho visível corre ao longo de cada curva — bevel_factor start/end);
  0,6–1,2 s  reator         anéis concêntricos finos (linha, cabo de fios, régua, 2 anéis de segmentos) surgem
                            e giram em sentidos/velocidades diferentes;
  1,0–2,0 s  segmentos      os 12 segmentos acendem um a um;
  2,0–2,5 s  ignição        o núcleo acende em pulso ciano-branco e uma onda fina em anel se expande;
  2,5–3,2 s  abertura       o reator cresce até sair do quadro e tudo se dissolve no branco (o painel entra
                            por baixo, em código).

Linguagem v63: azul #1D5BFF → céu #6FA8FF → ciano #38D3FF sobre branco-gelo #F7FAFF → branco. Nada de chão,
sala ou cinza. O "brilho" num fundo claro não pode ser aditivo (luz sobre branco some): a cena é renderizada
com fundo transparente e o compositor pousa sobre o branco duas névoas coloridas (desfoque da própria imagem)
antes da imagem nítida — o halo azul que dá a sensação de luz. Sem texto queimado: marca e motores ficam em
código por cima do vídeo.

Todo valor animado é função pura do tempo (handler frame_change_pre) — reprodutível quadro a quadro, sem
keyframes soltos. Aleatoriedade com semente fixa.

Uso: blender -b --factory-startup -P v69_abertura_blender.py -- <largura> <altura> <pasta_saida> [q0 q1 [passo]]
     (quadros 1..192 = 3,2 s a 60 fps; passo > 1 = prova rápida)
"""
import bpy
import bmesh
import math
import os
import random
import sys
from mathutils import Vector, Quaternion

argv = sys.argv[sys.argv.index('--') + 1:]
W, H, SAIDA = int(argv[0]), int(argv[1]), argv[2]
Q0, Q1 = (int(argv[3]), int(argv[4])) if len(argv) > 4 else (1, 192)
PASSO = int(argv[5]) if len(argv) > 5 else 1
FPS, NQ = 60, 192
VERTICAL = H > W * 1.2
RND = random.Random(69)
DIAG = os.environ.get('V69_DIAG', '')       # 'semdof', 'semnevoa' — só para diagnóstico


def lin(h):
    h = h.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((x + .055) / 1.055) ** 2.4 if x > .04045 else x / 12.92 for x in c)


COB, CEU, CIA, GELO, TINTA = lin('#1D5BFF'), lin('#6FA8FF'), lin('#38D3FF'), lin('#BFD3FF'), lin('#0B3D91')
BRANCO_CIANO = lin('#E6FBFF')
FUNDO0, FUNDO1 = lin('#F7FAFF'), (1.0, 1.0, 1.0)


def cl(x, a=0., b=1.): return a if x < a else b if x > b else x
def ss(a, b, x): u = cl((x - a) / (b - a)); return u * u * (3 - 2 * u)
def mix(a, b, u): return tuple(p + (q - p) * u for p, q in zip(a, b))
def eio(u): u = cl(u); return 4 * u ** 3 if u < .5 else 1 - (-2 * u + 2) ** 3 / 2
def eout(u): u = cl(u); return 1 - (1 - u) ** 3


# ------------------------------------------------------------------ cena base
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.eevee.taa_render_samples = 64
# DOF por jitter de câmera: o DOF de pós-processo do EEVEE lê a profundidade, que material BLENDED não grava —
# desfocava o reator inteiro mesmo em foco (medido 18/11). Com jitter cada amostra é uma câmera real.
sc.eevee.use_bokeh_jittered = True
sc.render.fps = FPS
sc.frame_start, sc.frame_end, sc.frame_step = Q0, Q1, PASSO
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.film_transparent = True
sc.render.use_lock_interface = True
sc.view_settings.view_transform = 'Standard'; sc.view_settings.look = 'None'
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_depth = '16'
sc.render.image_settings.color_mode = 'RGB'
sc.render.filepath = os.path.join(SAIDA, '')
wd = bpy.data.worlds.new('w'); sc.world = wd
try:
    wd.use_nodes = True; wd.node_tree.nodes['Background'].inputs[0].default_value = (*FUNDO0, 1)
except (AttributeError, KeyError):       # mundo sem nós nesta versão
    wd.color = FUNDO0


def link(o, pai=None):
    sc.collection.objects.link(o)
    if pai is not None: o.parent = pai
    return o


def vazio(nome, pai=None):
    return link(bpy.data.objects.new(nome, None), pai)


# ------------------------------------------------------------------ materiais
def mat_cor(nome):
    """Emissão + transparência guiadas por objeto: Object Info Color = cor, Alpha = opacidade."""
    m = bpy.data.materials.new(nome)
    nt = m.node_tree; N = nt.nodes; L = nt.links
    for n in list(N): N.remove(n)
    oi = N.new('ShaderNodeObjectInfo')
    em = N.new('ShaderNodeEmission'); em.inputs[1].default_value = 1.0
    tr = N.new('ShaderNodeBsdfTransparent')
    mx = N.new('ShaderNodeMixShader'); out = N.new('ShaderNodeOutputMaterial')
    L.new(oi.outputs['Color'], em.inputs[0]); L.new(oi.outputs['Alpha'], mx.inputs[0])
    L.new(tr.outputs[0], mx.inputs[1]); L.new(em.outputs[0], mx.inputs[2]); L.new(mx.outputs[0], out.inputs[0])
    m.surface_render_method = 'BLENDED'
    m.use_backface_culling = False
    return m


def mat_fita():
    """Fita: U (UV.x) corre 0→1 ao longo do trecho VISÍVEL (medido 18/11 no Blender 5.2: o UV acompanha o
    bevel_factor). Cauda transparente (U≈0) → cabeça opaca (U≈1); cor azul na cauda → ciano na cabeça,
    deslocada pela semente da fita (Object Info Color.r). Opacidade geral = Object Info Alpha."""
    m = bpy.data.materials.new('fita')
    nt = m.node_tree; N = nt.nodes; L = nt.links
    for n in list(N): N.remove(n)
    tc = N.new('ShaderNodeTexCoord'); sep = N.new('ShaderNodeSeparateXYZ'); L.new(tc.outputs['UV'], sep.inputs[0])
    oi = N.new('ShaderNodeObjectInfo'); so = N.new('ShaderNodeSeparateColor'); L.new(oi.outputs['Color'], so.inputs[0])
    # cor: rampa(0,55·U + 0,45·semente)
    mu = N.new('ShaderNodeMath'); mu.operation = 'MULTIPLY_ADD'; mu.inputs[1].default_value = .55
    L.new(sep.outputs[0], mu.inputs[0])
    ms = N.new('ShaderNodeMath'); ms.operation = 'MULTIPLY'; ms.inputs[1].default_value = .45
    L.new(so.outputs[0], ms.inputs[0]); L.new(ms.outputs[0], mu.inputs[2])
    rp = N.new('ShaderNodeValToRGB'); e = rp.color_ramp.elements
    e[0].position, e[0].color = 0.0, (*lin('#4E9CFF'), 1); e[1].position, e[1].color = 1.0, (*CIA, 1)
    e.new(.45).color = (*lin('#3A8DFF'), 1)
    L.new(mu.outputs[0], rp.inputs[0])
    # alfa ao longo: smoothstep(0, 0,55, U) · (1 − smoothstep(0,985, 1, U)) · Alpha do objeto
    a1 = N.new('ShaderNodeMapRange'); a1.interpolation_type = 'SMOOTHSTEP'; a1.inputs[1].default_value = 0; a1.inputs[2].default_value = .55
    L.new(sep.outputs[0], a1.inputs[0])
    a2 = N.new('ShaderNodeMapRange'); a2.interpolation_type = 'SMOOTHSTEP'
    a2.inputs[1].default_value = .985; a2.inputs[2].default_value = 1.0; a2.inputs[3].default_value = 1; a2.inputs[4].default_value = .35
    L.new(sep.outputs[0], a2.inputs[0])
    p1 = N.new('ShaderNodeMath'); p1.operation = 'MULTIPLY'; L.new(a1.outputs[0], p1.inputs[0]); L.new(a2.outputs[0], p1.inputs[1])
    p2 = N.new('ShaderNodeMath'); p2.operation = 'MULTIPLY'; L.new(p1.outputs[0], p2.inputs[0]); L.new(oi.outputs['Alpha'], p2.inputs[1])
    em = N.new('ShaderNodeEmission'); em.inputs[1].default_value = 1.0; L.new(rp.outputs[0], em.inputs[0])
    tr = N.new('ShaderNodeBsdfTransparent'); mx = N.new('ShaderNodeMixShader'); out = N.new('ShaderNodeOutputMaterial')
    L.new(p2.outputs[0], mx.inputs[0]); L.new(tr.outputs[0], mx.inputs[1]); L.new(em.outputs[0], mx.inputs[2])
    L.new(mx.outputs[0], out.inputs[0])
    m.surface_render_method = 'BLENDED'; m.use_backface_culling = False
    return m


def mat_nucleo():
    """Esfera do núcleo: vidro claro (miolo quase branco, borda azul por fresnel). Na ignição a cor do objeto
    (Object Info Color) empurra tudo para ciano-branco; Alpha = opacidade."""
    m = bpy.data.materials.new('nucleo')
    nt = m.node_tree; N = nt.nodes; L = nt.links
    for n in list(N): N.remove(n)
    lw = N.new('ShaderNodeLayerWeight'); lw.inputs[0].default_value = .35
    rp = N.new('ShaderNodeValToRGB'); e = rp.color_ramp.elements
    e[0].position, e[0].color = 0.0, (*lin('#EEF6FF'), 1); e[1].position, e[1].color = 1.0, (*CEU, 1)
    e.new(.55).color = (*lin('#CFE3FF'), 1)
    L.new(lw.outputs['Facing'], rp.inputs[0])
    oi = N.new('ShaderNodeObjectInfo'); so = N.new('ShaderNodeSeparateColor'); L.new(oi.outputs['Color'], so.inputs[0])
    mxc = N.new('ShaderNodeMix'); mxc.data_type = 'RGBA'
    L.new(so.outputs[0], mxc.inputs[0]); L.new(rp.outputs[0], mxc.inputs[6]); mxc.inputs[7].default_value = (*BRANCO_CIANO, 1)
    em = N.new('ShaderNodeEmission'); em.inputs[1].default_value = 1.0; L.new(mxc.outputs[2], em.inputs[0])
    tr = N.new('ShaderNodeBsdfTransparent'); mx = N.new('ShaderNodeMixShader'); out = N.new('ShaderNodeOutputMaterial')
    L.new(oi.outputs['Alpha'], mx.inputs[0]); L.new(tr.outputs[0], mx.inputs[1]); L.new(em.outputs[0], mx.inputs[2])
    L.new(mx.outputs[0], out.inputs[0])
    m.surface_render_method = 'BLENDED'
    return m


def mat_halo():
    """Disco de brilho: gradiente radial (1 no centro → 0 na borda, quadrático) × Alpha do objeto."""
    m = bpy.data.materials.new('halo')
    nt = m.node_tree; N = nt.nodes; L = nt.links
    for n in list(N): N.remove(n)
    tc = N.new('ShaderNodeTexCoord'); ln = N.new('ShaderNodeVectorMath'); ln.operation = 'LENGTH'
    L.new(tc.outputs['Object'], ln.inputs[0])
    mr = N.new('ShaderNodeMapRange'); mr.interpolation_type = 'SMOOTHERSTEP'
    mr.inputs[1].default_value = 1.0; mr.inputs[2].default_value = 0.0
    L.new(ln.outputs['Value'], mr.inputs[0])
    pw = N.new('ShaderNodeMath'); pw.operation = 'POWER'; pw.inputs[1].default_value = 2.2; L.new(mr.outputs[0], pw.inputs[0])
    oi = N.new('ShaderNodeObjectInfo')
    pa = N.new('ShaderNodeMath'); pa.operation = 'MULTIPLY'; L.new(pw.outputs[0], pa.inputs[0]); L.new(oi.outputs['Alpha'], pa.inputs[1])
    p3 = N.new('ShaderNodeMath'); p3.operation = 'POWER'; p3.inputs[1].default_value = 3.0; L.new(pw.outputs[0], p3.inputs[0])
    mc = N.new('ShaderNodeMix'); mc.data_type = 'RGBA'; L.new(p3.outputs[0], mc.inputs[0])
    L.new(oi.outputs['Color'], mc.inputs[6]); mc.inputs[7].default_value = (1, 1, 1, 1)
    em = N.new('ShaderNodeEmission'); em.inputs[1].default_value = 1.0; L.new(mc.outputs[2], em.inputs[0])
    tr = N.new('ShaderNodeBsdfTransparent'); mx = N.new('ShaderNodeMixShader'); out = N.new('ShaderNodeOutputMaterial')
    L.new(pa.outputs[0], mx.inputs[0]); L.new(tr.outputs[0], mx.inputs[1]); L.new(em.outputs[0], mx.inputs[2])
    L.new(mx.outputs[0], out.inputs[0])
    m.surface_render_method = 'BLENDED'
    return m


M_COR, M_FITA, M_NUC, M_HALO = mat_cor('cor'), mat_fita(), mat_nucleo(), mat_halo()


# ------------------------------------------------------------------ geometria
def setor(nome, r0, r1, a0, a1, pai, z=0.0, n=None):
    """Faixa plana de anel entre os raios r0..r1 e os ângulos a0..a1 (rad)."""
    n = n or max(6, int(abs(a1 - a0) / (2 * math.pi) * 256))
    vs, fs = [], []
    for i in range(n + 1):
        a = a0 + (a1 - a0) * i / n
        vs += [(r0 * math.cos(a), r0 * math.sin(a), z), (r1 * math.cos(a), r1 * math.sin(a), z)]
        if i: fs.append((2 * i - 2, 2 * i - 1, 2 * i + 1, 2 * i))
    me = bpy.data.meshes.new(nome); me.from_pydata(vs, [], fs); me.materials.append(M_COR)
    return link(bpy.data.objects.new(nome, me), pai)


def disco(nome, r, pai, mat, z=0.0):
    bm = bmesh.new(); bmesh.ops.create_circle(bm, cap_ends=True, radius=r, segments=96)
    me = bpy.data.meshes.new(nome); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = link(bpy.data.objects.new(nome, me), pai); o.location.z = z
    return o


ANIM = []          # (objeto, função t -> None)

# raiz do reator (escala/abertura) e da cena de fitas
reator = vazio('reator')
nuvem = vazio('nuvem')


def giro(nome, w, fase=0.0):
    e = vazio(nome, reator)
    ANIM.append((e, lambda t, e=e: setattr(e.rotation_euler, 'z', fase + w * t)))
    return e


def surge(t, t0, dur=.55):
    return eout((t - t0) / dur)


def fade_abertura(t):
    return 1 - ss(2.6, 3.0, t)


# anéis externos — linhas finas contínuas
for nome, r, larg, cor, op, t0 in (('linha_ext', 1.115, .0045, CEU, .75, .70), ('linha_1', 1.0, .0075, COB, .95, .62),
                                    ('linha_int', .455, .004, lin('#3F7BFF'), .8, .80)):
    o = setor(nome, r - larg / 2, r + larg / 2, 0, 2 * math.pi, reator)

    def f(t, o=o, cor=cor, op=op, t0=t0):
        u = surge(t, t0); o.color = (*cor, op * u * fade_abertura(t)); o.scale = (.86 + .14 * u,) * 3
    ANIM.append((o, f))

# cabo: dezenas de fios finos no anel 0,84–0,93 (a faixa azul densa da referência), girando
g_cabo = giro('g_cabo', -.55)
for k in range(46):
    r = .842 + .088 * RND.random(); larg = .0022 + .0028 * RND.random()
    a0 = RND.random() * 2 * math.pi; arco = 2 * math.pi * (.55 + .45 * RND.random())
    o = setor(f'cabo{k}', r - larg / 2, r + larg / 2, a0, a0 + arco, g_cabo)
    cor = mix(lin('#4A86FF'), CIA, RND.random() ** 1.5); op = .35 + .5 * RND.random(); t0 = .62 + .35 * RND.random()

    def f(t, o=o, cor=cor, op=op, t0=t0):
        u = surge(t, t0, .5); o.color = (*cor, op * u * fade_abertura(t))
    ANIM.append((o, f))

# régua: 90 riscos radiais
g_regua = giro('g_regua', .22)
for k in range(90):
    a = k * 2 * math.pi / 90; maior = k % 5 == 0
    o = setor(f'risco{k}', .735, .775 if maior else .755, a - .0042, a + .0042, g_regua, n=1)

    def f(t, o=o, k=k, maior=maior):
        u = surge(t, .75 + k * .0035, .3); o.color = (*(COB if maior else CEU), (.9 if maior else .55) * u * fade_abertura(t))
    ANIM.append((o, f))

# segmentos (os que acendem em sequência): 8 no anel 0,655–0,700 e 4 no 0,525–0,565
SEGS = []
g_s8 = giro('g_s8', .9, .2)
for k in range(8):
    a0 = k * 2 * math.pi / 8 + .06
    SEGS.append((setor(f'seg8_{k}', .655, .700, a0, a0 + 2 * math.pi / 8 - .12, g_s8), .6775, a0, a0 + 2 * math.pi / 8 - .12))
g_s4 = giro('g_s4', -1.45, .7)
for k in range(4):
    a0 = k * 2 * math.pi / 4 + .14
    SEGS.append((setor(f'seg4_{k}', .525, .565, a0, a0 + 2 * math.pi / 4 - .28, g_s4), .545, a0, a0 + 2 * math.pi / 4 - .28))
# ordem de acendimento: alterna os dois anéis (8 externos + 4 internos), 1,00 → 1,92 s
ORDEM = [0, 8, 1, 2, 9, 3, 4, 10, 5, 6, 11, 7]
for n, i in enumerate(ORDEM):
    o, rm, a0, a1 = SEGS[i]; ta = 1.0 + n * .077

    def f(t, o=o, ta=ta):
        u = surge(t, .78, .45); aceso = ss(ta, ta + .07, t)
        flash = math.exp(-max(0., t - ta - .05) * 9) * aceso     # estoura um pouco ao acender e assenta
        cor = mix(GELO, CIA, aceso); cor = mix(cor, BRANCO_CIANO, .45 * flash)
        o.color = (*cor, (.38 + .62 * aceso) * u * fade_abertura(t))
    ANIM.append((o, f))
    # halo do segmento (faixa larga e suave por trás) — dá a luz do segmento aceso no fundo claro
    # halo em 3 faixas sobrepostas cada vez mais largas (degradê radial barato, sem borda dura)
    for j, (dr, peso) in enumerate(((.022, .45), (.042, .3), (.07, .2))):
        h = setor(f'{o.name}_halo{j}', rm - dr, rm + dr, a0 - dr * .6, a1 + dr * .6, o.parent, z=-.002 - j * .001)

        def fh(t, h=h, ta=ta, peso=peso):
            aceso = ss(ta, ta + .07, t); flash = math.exp(-max(0., t - ta - .05) * 7) * aceso
            h.color = (*CIA, peso * (.22 + .4 * flash) * aceso * fade_abertura(t))
        ANIM.append((h, fh))

# núcleo, brilho e onda de choque
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=.30)
nuc = bpy.context.object; nuc.name = 'nucleo'; nuc.parent = reator; nuc.data.materials.append(M_NUC)
bpy.ops.object.shade_smooth()


def f_nuc(t):
    u = surge(t, .9, .5)
    ign = ss(2.0, 2.12, t) * (1 - .55 * ss(2.25, 2.7, t))          # acende e assenta num nível alto
    nuc.color = (cl(ign + .15 * ss(1.4, 2.0, t)), 0, 0, u * fade_abertura(t))
    s = .8 + .2 * u + .08 * math.exp(-max(0., t - 2.05) * 10) * ss(2.0, 2.05, t)
    nuc.scale = (s,) * 3
ANIM.append((nuc, f_nuc))

halo = disco('halo_nucleo', 1.0, reator, M_HALO, z=-.05)


def f_halo(t):
    pre = .25 * ss(1.3, 2.0, t)
    ign = math.exp(-max(0., t - 2.02) * 3.2) * ss(1.98, 2.06, t)
    halo.color = (*CIA, cl(pre + 1.0 * ign) * fade_abertura(t))
    s = .55 + .25 * pre + 1.9 * ign
    halo.scale = (s,) * 3
ANIM.append((halo, f_halo))

halo2 = disco('halo_largo', 1.0, None, M_HALO, z=-.3)


def f_halo2(t):
    ign = math.exp(-max(0., t - 2.04) * 2.6) * ss(1.98, 2.1, t)
    halo2.color = (*CEU, .55 * ign * (1 - ss(2.55, 2.95, t)))
    halo2.scale = (1.2 + 3.8 * eout((t - 1.98) / .9),) * 3
ANIM.append((halo2, f_halo2))


def clarao(t):
    return math.exp(-max(0., t - 2.03) * 6) * ss(1.97, 2.03, t)

ONDAS = []
for k, (larg, op, atr, cor) in enumerate(((.016, 1.0, 0.0, CIA), (.05, .20, .015, CEU), (.006, .75, .10, lin('#3F7BFF')))):
    o = setor(f'onda{k}', 1 - larg / 2, 1 + larg / 2, 0, 2 * math.pi, None)

    def f(t, o=o, op=op, atr=atr, cor=cor):
        u = cl((t - 2.02 - atr) / .78)
        o.scale = (.42 + 7.5 * eout(u) ** 1.15,) * 3
        o.color = (*cor, op * (1 - ss(.0, 1.0, u)) * (u > 0))
    ANIM.append((o, f))

# ------------------------------------------------------------------ fitas de luz
NF = 260
FITAS = []
for k in range(NF):
    th_pouso = RND.random() * 2 * math.pi
    rl = .86 + .07 * RND.random() if RND.random() < .78 else .97 + .12 * RND.random()
    r0 = 4.1 + 1.9 * RND.random()
    phi = 1.7 + 1.5 * RND.random()                 # quanto a fita gira até pousar (espiral anti-horária)
    enrola = .5 + 1.8 * RND.random()               # quanto contorna o anel depois de pousar
    z0 = -3.2 + 4.6 * RND.random()
    cu = bpy.data.curves.new(f'fita{k}', 'CURVE'); cu.dimensions = '3D'
    cu.bevel_depth = .0026 + .0024 * RND.random(); cu.bevel_resolution = 1
    cu.bevel_factor_mapping_start = cu.bevel_factor_mapping_end = 'SPLINE'
    sp = cu.splines.new('POLY'); NP = 110; sp.points.add(NP - 1)
    frac = .78
    for i, p in enumerate(sp.points):
        s = i / (NP - 1)
        if s <= frac:
            u = s / frac
            r = rl + (r0 - rl) * (1 - u) ** 2.1
            a = th_pouso - phi * (1 - u) ** 1.25
            z = z0 * (1 - u) ** 2.4
        else:
            u = (s - frac) / (1 - frac)
            r = rl; a = th_pouso + enrola * u; z = 0
        p.co = (r * math.cos(a), r * math.sin(a), z, 1)
    cu.materials.append(M_FITA)
    o = link(bpy.data.objects.new(f'fita{k}', cu), nuvem)
    fica = RND.random() < .5                        # metade fica desenhada (fio), metade passa como cometa
    t0 = -.28 + .86 * RND.random() ** 1.2
    dur = .62 + .38 * RND.random()
    cauda = .16 + .28 * RND.random()
    semente = RND.random()
    op = (.55 + .45 * RND.random()) * (.7 if fica else 1.0)
    FITAS.append(o)

    def f(t, o=o, cu=cu, fica=fica, t0=t0, dur=dur, cauda=cauda, semente=semente, op=op):
        cab = eio((t - t0) / dur) if t > t0 else 0.0
        if fica:
            ini = 0.0
            nivel = op * (1 - .5 * ss(1.35, 2.0, t))        # assenta para o reator mandar
        else:
            ini = cl(cab - cauda) if cab < 1 else cl(1 - cauda + (t - t0 - dur) / .32 * cauda)
            nivel = op
        fim = max(cab, ini + 1e-4)
        cu.bevel_factor_start, cu.bevel_factor_end = ini, fim
        vis = 1.0 if fim - ini > .004 else 0.0
        o.color = (semente, 0, 0, min(1., nivel * (1 + .7 * clarao(t))) * vis * (1 - ss(2.15, 2.8, t)) * ss(-.02, .1, t))
    ANIM.append((o, f))

# ------------------------------------------------------------------ poeira de luz (pouca, nítida)
for k in range(64):
    bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=2, radius=.006 + .012 * RND.random() ** 2)
    me = bpy.data.meshes.new(f'p{k}'); bm.to_mesh(me); bm.free(); me.materials.append(M_COR)
    o = link(bpy.data.objects.new(f'poeira{k}', me))
    a = RND.random() * 2 * math.pi; r = 1.3 + 4.2 * RND.random() ** .8; z = -3.0 + 4.2 * RND.random()
    w = (.10 + .18 * RND.random()) * (1 if RND.random() < .85 else -1)
    cor = (CEU, CIA, COB)[k % 3]; fase = RND.random() * 6.28; op = .55 + .45 * RND.random()

    def f(t, o=o, a=a, r=r, z=z, w=w, cor=cor, fase=fase, op=op):
        aa = a + w * t; rr = r * (1 - .06 * t)
        o.location = (rr * math.cos(aa), rr * math.sin(aa), z)
        cint = .65 + .35 * math.sin(fase + t * 7)
        o.color = (*cor, op * cint * ss(.1, .6, t) * (1 - ss(2.3, 2.95, t)))
    ANIM.append((o, f))

# ------------------------------------------------------------------ abertura (o reator cresce e sai)
def f_reator(t):
    u = ss(2.48, 3.12, t)
    s = 1 + 6.5 * u ** 2.2
    reator.scale = (s,) * 3
    nuvem.scale = (1 + .9 * u ** 1.6,) * 3
    nuvem.rotation_euler.z = -.05 * t - .25 * u
ANIM.append((reator, f_reator))

# ------------------------------------------------------------------ câmera
camd = bpy.data.cameras.new('cam'); camd.sensor_fit = 'HORIZONTAL'; camd.sensor_width = 36
# mesma distância; no vertical a lente fecha para o reator ocupar ~70 % da largura VISÍVEL do celular
# (o 9:16 em object-fit:cover num 390×844 mostra ~82 % da largura do vídeo)
camd.lens = 84.5 if VERTICAL else 52.0
camd.clip_start, camd.clip_end = .1, 60
camd.dof.use_dof = 'semdof' not in DIAG; camd.dof.aperture_fstop = 1.4 if not VERTICAL else 3.7     # desfoque ∝ f²/N: mesmo desfoque relativo
cam = link(bpy.data.objects.new('cam', camd)); sc.camera = cam
camd.dof.focus_object = reator          # foco no plano do reator (distância via handler não pegava: medido 18/11)


def f_cam(t):
    u = eio(t / 3.2)
    d = 9.6 - 1.35 * u                       # push-in
    ax = .075 - .10 * u; ay = -.045 + .06 * u  # leve órbita (paralaxe real entre fitas e reator)
    p = Vector((d * math.sin(ax), d * math.sin(ay), d * math.cos(ax) * math.cos(ay)))
    cam.location = p
    q = (-p).to_track_quat('-Z', 'Y')
    roll = Quaternion((0, 0, 1), math.radians(-1.2 + 3.2 * u))
    cam.rotation_mode = 'QUATERNION'; cam.rotation_quaternion = q @ roll
ANIM.append((cam, f_cam))

# ------------------------------------------------------------------ compositor (névoa colorida sobre o branco)
ng = bpy.data.node_groups.new('comp', 'CompositorNodeTree')
sc.compositing_node_group = ng
ng.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
CN = ng.nodes; CL = ng.links
rl_ = CN.new('CompositorNodeRLayers')
esc = W / 2160.0 if not VERTICAL else W / 1080.0 * .75


def borrao(px, fator):
    b = CN.new('CompositorNodeBlur')
    b.inputs['Size'].default_value = (px * esc, px * esc)
    try: b.inputs['Type'].default_value = 'Gaussian'
    except (TypeError, KeyError): pass      # o tipo é menu do nó; ausente → padrão
    CL.new(rl_.outputs['Image'], b.inputs['Image'])
    return b, fator


fundo_rgb = CN.new('CompositorNodeRGB')
fundo_rgb.outputs[0].default_value = (*FUNDO0, 1)
atual = fundo_rgb.outputs[0]
for px, fator in (() if 'semnevoa' in DIAG else ((110, .38), (30, .5), (6, .3))):
    b, fat = borrao(px, fator)
    ao = CN.new('CompositorNodeAlphaOver'); ao.inputs['Factor'].default_value = fat
    CL.new(atual, ao.inputs['Background']); CL.new(b.outputs[0], ao.inputs['Foreground'])
    atual = ao.outputs[0]
ao = CN.new('CompositorNodeAlphaOver')
CL.new(atual, ao.inputs['Background']); CL.new(rl_.outputs['Image'], ao.inputs['Foreground'])
go = CN.new('NodeGroupOutput'); CL.new(ao.outputs[0], go.inputs[0])


def f_fundo(t):
    fundo_rgb.outputs[0].default_value = (*mix(FUNDO0, FUNDO1, ss(2.4, 3.1, t)), 1)


# ------------------------------------------------------------------ handler
def aplicar(scene, *_):
    t = (scene.frame_current - 1) / FPS
    for _o, fn in ANIM: fn(t)
    f_fundo(t)


bpy.app.handlers.frame_change_pre.append(aplicar)
aplicar(sc)
print(f'CENA-MONTADA {W}x{H} fitas={NF} objetos={len(bpy.data.objects)} quadros {Q0}..{Q1}/{PASSO}', flush=True)
os.makedirs(SAIDA, exist_ok=True)
bpy.ops.render.render(animation=True)
print('RENDER-FIM', flush=True)
