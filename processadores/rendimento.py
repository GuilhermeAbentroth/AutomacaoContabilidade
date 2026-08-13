import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class RendimentoProcessor(BaseProcessor):
    """
    Extrato Detalhado da Conta (ex.: Banco Rendimento).
    Layout em colunas: Data | Hora | Histórico | Documento | Débito | Crédito | Saldo.
    Célula "Documento" costuma quebrar em várias linhas (POS / código / "- Aut." / nº),
    o que bagunça a ordem visual — por isso a extração usa a ordem de leitura do PDF
    (que preserva a ordem lógica das colunas) e classifica cada valor monetário pela
    posição X, em vez de tentar reconstruir linhas por proximidade vertical.
    """

    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "RENDIMENTO"

    # Faixas de coluna (posição X) só para os valores monetários
    COL_DEBITO = (385, 445)
    COL_CREDITO = (445, 510)

    PALAVRA_TITULO = re.compile(r'[A-ZÀ-Ú][a-zà-úçã]*\.?,?')
    PALAVRA_MAIUSCULA = re.compile(r'[A-ZÀ-Ú]+\.?')
    PALAVRA_MINUSCULA = re.compile(r'[a-zà-úçã]+\.?')

    def processar(self, arquivo, log_func):
        log_func(f"Lendo Rendimento (Extrato Detalhado): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            registros = []
            transacao_atual = None
            parar = False

            for page in doc:
                if parar:
                    break

                # words: (x0, y0, x1, y1, texto, block_no, line_no, word_no) na ordem de leitura do PDF
                for w in page.get_text("words"):
                    if parar:
                        break

                    x0, texto = w[0], w[4]
                    texto_norm = self.remover_acentos(texto)

                    # Fim do extrato: bloco de resumo "DISPONÍVEL em .../ Limite Cheque
                    # Especial / Saldo Bloqueado etc." tem layout diferente e não deve
                    # ser lido como lançamento.
                    if texto_norm == "DISPONIVEL":
                        transacao_atual = None
                        parar = True
                        break

                    # Nova data (DD/MM/AAAA nas transações normais, ou DD/MM nos
                    # marcadores "Saldo anterior" / saldo final do dia — esses nunca
                    # têm valor de Débito/Crédito, então são descartados de qualquer
                    # forma; não vale a pena inferir o ano para eles)
                    m_data_completa = re.fullmatch(r'\d{2}/\d{2}/\d{4}', texto)
                    m_data_curta = re.fullmatch(r'\d{2}/\d{2}', texto)
                    if m_data_completa or m_data_curta:
                        if transacao_atual:
                            valida = self._finalizar_e_validar(transacao_atual)
                            if valida:
                                registros.append(valida)

                        transacao_atual = {
                            "data": texto if m_data_completa else None,
                            "historico": [],
                            "valor": None,
                            "tipo": None,
                        }
                        continue

                    # Hora (coluna própria, sem uso no lançamento final)
                    if re.fullmatch(r'\d{2}:\d{2}', texto):
                        continue

                    # Valor monetário: decide Débito/Crédito pela posição X.
                    # A coluna Saldo (mais à direita) é só informativa e é ignorada.
                    if re.fullmatch(r'\d{1,3}(?:\.\d{3})*,\d{2}', texto):
                        if not transacao_atual or transacao_atual["valor"] is not None:
                            continue
                        v = self.limpar_valor(texto)
                        if v == 0:
                            continue
                        if self.COL_DEBITO[0] <= x0 < self.COL_DEBITO[1]:
                            transacao_atual["valor"] = -abs(v)
                            transacao_atual["tipo"] = "DEBITO"
                        elif self.COL_CREDITO[0] <= x0 < self.COL_CREDITO[1]:
                            transacao_atual["valor"] = abs(v)
                            transacao_atual["tipo"] = "CREDITO"
                        # fora dessas faixas -> coluna Saldo, ignorado
                        continue

                    # Texto livre (histórico, código de documento, "Cp :xxxx-NOME" etc.)
                    if transacao_atual:
                        transacao_atual["historico"].append(texto)

            if transacao_atual:
                valida = self._finalizar_e_validar(transacao_atual)
                if valida:
                    registros.append(valida)

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0])

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro Crítico Rendimento {arquivo}: {e}", "erro")
            return None

    def _eh_ruido(self, tok):
        """Identifica fragmentos da célula "Documento" (códigos de autenticação,
        números de agência/conta) que não fazem parte da descrição real."""
        t = tok.strip(" -:")
        if not t or t == "-":
            return True
        if t.upper() in ("POS", "SALDO", "CP", "AUT", "AUT."):
            return True
        # Número puro (documento, agência, conta): 4+ dígitos seguidos
        if re.fullmatch(r'\d{4,}', t):
            return True
        if len(t) < 5:
            return False
        # Código alfanumérico de autenticação (mistura letra + dígito)
        if re.search(r'\d', t) and re.search(r'[A-Za-z]', t):
            return True
        # Código só de letras mas com capitalização irregular (ex.: "iHbhAUj"),
        # ao contrário de uma palavra normal em Título, MAIÚSCULA ou minúscula
        if (not self.PALAVRA_TITULO.fullmatch(t)
                and not self.PALAVRA_MAIUSCULA.fullmatch(t)
                and not self.PALAVRA_MINUSCULA.fullmatch(t)):
            return True
        return False

    def _limpar_historico(self, palavras):
        limpo = []
        for tok in palavras:
            # "Cp :12345678-NOME" -> remove o prefixo do código, mantém o nome
            t = re.sub(r'^:\d+-', '', tok)
            if self._eh_ruido(t):
                continue
            limpo.append(t)
        texto = " ".join(limpo)
        return re.sub(r'\s+', ' ', texto).strip()

    def _finalizar_e_validar(self, t):
        if t["valor"] is None or not t["data"]:
            return None

        hist = self._limpar_historico(t["historico"])
        if len(hist) < 3:
            return None

        return {
            "DATA": t["data"],
            "HISTORICO": self.remover_acentos(hist).upper(),
            "VALOR": t["valor"],
            "TIPO": t["tipo"],
        }
