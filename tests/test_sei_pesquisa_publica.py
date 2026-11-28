"""27/11/2026 — pesquisa PÚBLICA do SEI-RJ para os RESTRITO da unidade: a árvore e os links dos documentos."""
from compliance_agent.sei import pesquisa_publica as PP

_LINHA = ('<tr class="infraTr{c}"><td class="no-print">&nbsp;</td><td data-label="Processo / Documento">{doc}</td>'
          '<td data-label="Tipo">{tipo}</td><td data-label="Data">01/02/2025</td><td>02/02/2025</td>'
          '<td data-label="Unidade">SEDEC/X</td></tr>')
_LINK = ("<a href=\"javascript:void(0);\" onclick=\"window.open('md_pesq_documento_consulta_externa.php?d-abc&amp;"
         "x=1');\">{n}</a>")


def _pagina(*linhas):
    return ('<p>Restrito - Para visualizar o conteúdo deste processo, entre em contato com a unidade.</p>'
            '<table id="tblDocumentos"><tr><th>Processo / Documento</th></tr>' + "".join(linhas) + "</table>")


def test_documento_com_link_e_sem_link_e_o_aviso_nao_e_veredito():
    p = _pagina(_LINHA.format(c="Clara", doc=_LINK.format(n="111"), tipo="Ofício 6"),
                _LINHA.format(c="Escura", doc="222", tipo="Nota fiscal"))
    a = PP.ler_arvore(p)
    assert [(d.numero, d.tipo, d.unidade) for d in a.documentos] == [("111", "Ofício 6", "SEDEC/X"),
                                                                     ("222", "Nota fiscal", "SEDEC/X")]
    assert a.documentos[0].url == PP.BASE + "md_pesq_documento_consulta_externa.php?d-abc&x=1" and a.documentos[1].url is None
    assert PP.classificar(a) == PP.PUBLICO_COM_DOCS                 # o aviso «Restrito» aparece e os docs abrem


def test_so_arvore_e_nao_achado():
    assert PP.classificar(PP.ler_arvore(_pagina(_LINHA.format(c="Clara", doc="222", tipo="X")))) == PP.SO_ARVORE
    assert PP.classificar(PP.ler_arvore("<html>nada</html>")) == PP.NAO_ACHADO and PP.classificar(None) == PP.NAO_ACHADO


def test_resposta_do_ajax_em_iso_8859_1():
    assert PP.resposta_ajax('{"html": "Pregão"}'.encode("iso-8859-1")) == {"html": "Pregão"}
