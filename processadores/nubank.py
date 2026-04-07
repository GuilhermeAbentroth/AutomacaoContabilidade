import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class NubankProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "NUBANK"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo NUBANK (Regra do Dia c/ Blindagem Anti-Subtotais): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            linhas = []

            # 1. Agrupamento rigoroso por linhas fatiadas
            for page in doc:
                words = page.get_text("words")
                if not words: continue

                words.sort(key=lambda w: (w[1], w[0]))

                linha_atual = []
                y_ref = None

                for w in words:
                    if y_ref is None:
                        linha_atual.append(w)
                        y_ref = w[1]
                    elif abs(w[1] - y_ref) <= 5:
                        linha_atual.append(w)
                    else:
                        linha_atual.sort(key=lambda x: x[0])
                        linhas.append(" ".join([x[4] for x in linha_atual]))
                        linha_atual = [w]
                        y_ref = w[1]

                if linha_atual:
                    linha_atual.sort(key=lambda x: x[0])
                    linhas.append(" ".join([x[4] for x in linha_atual]))

            if not linhas:
                log_func(f"Aviso: Nenhuma linha de texto encontrada em {arquivo}", "erro")
                return None

            registros = []
            data_atual = None
            modo_atual = None  # Pode ser 'CREDITO', 'DEBITO' ou None
            transacao_atual = None

            meses = {
                "JAN": "01", "FEV": "02", "MAR": "03", "ABR": "04", "MAI": "05", "JUN": "06",
                "JUL": "07", "AGO": "08", "SET": "09", "OUT": "10", "NOV": "11", "DEZ": "12"
            }

            # Lixo Sistêmico (Cabeçalhos e rodapés de páginas)
            lixo = [
                "RENDIMENTO LÍQUIDO", "RENDIMENTO LIQUIDO", "SALDO INICIAL", "SALDO FINAL",
                "O SALDO LÍQUIDO", "O SALDO LIQUIDO", "NÃO NOS RESPONSABILIZAMOS",
                "NAO NOS RESPONSABILIZAMOS", "ASSEGURAMOS A AUTENTICIDADE", "NU FINANCEIRA",
                "CNPJ: 30.680", "MOVIMENTAÇÕES", "MOVIMENTACOES", "PÁGINA", "PAGINA",
                "TEM ALGUMA DÚVIDA", "TEM ALGUMA DUVIDA", "MANDE UMA MENSAGEM",
                "TIME DE ATENDIMENTO", "OU LIGUE", "0800", "4020", "ATENDIMENTO 24H",
                "CANAIS DE ATENDIMENTO", "OUVIDORIA", "NUBANK.COM.BR"
            ]

            # 2. Varredura com a Máquina de Blocos
            for linha in linhas:
                linha_str = linha.strip()
                if not linha_str: continue

                linha_up = linha_str.upper()

                # Ignora o Lixo do Rodapé
                if any(x in linha_up for x in lixo):
                    continue

                # =========================================================
                # EXTRAÇÃO DE DATA (Se achar, remove a data da linha)
                # =========================================================
                match_data = re.search(r'\b(\d{2})\s+(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s+(\d{4})\b',
                                       linha_up)
                if match_data:
                    dia = match_data.group(1)
                    mes = meses[match_data.group(2)]
                    ano = match_data.group(3)
                    data_atual = f"{dia}/{mes}/{ano}"

                    # Corta a data para avaliar apenas o restante do texto
                    linha_str = linha_str[:match_data.start()] + linha_str[match_data.end():]
                    linha_str = linha_str.strip()
                    linha_up = linha_str.upper()

                if not linha_str:
                    continue

                # =========================================================
                # TRANSIÇÃO DE BLOCOS (Fecha a transação e PULA A LINHA)
                # O "continue" é o segredo aqui: destrói o valor do subtotal!
                # =========================================================
                if "TOTAL DE ENTRADAS" in linha_up:
                    modo_atual = "CREDITO"
                    if transacao_atual:
                        self._fechar_transacao(transacao_atual, registros)
                        transacao_atual = None
                    continue

                if "TOTAL DE SAÍDAS" in linha_up or "TOTAL DE SAIDAS" in linha_up:
                    modo_atual = "DEBITO"
                    if transacao_atual:
                        self._fechar_transacao(transacao_atual, registros)
                        transacao_atual = None
                    continue

                if "SALDO DO DIA" in linha_up:
                    modo_atual = None
                    if transacao_atual:
                        self._fechar_transacao(transacao_atual, registros)
                        transacao_atual = None
                    continue

                    # Se estamos fora de um bloco diário válido, ignora.
                if not data_atual or not modo_atual:
                    continue

                # =========================================================
                # INÍCIO / CONTINUAÇÃO DE TRANSAÇÃO (Regex captura + ou -)
                # =========================================================
                match_valor = re.search(r'(?:^|\s)(?:[+-]\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})$', linha_str)

                if match_valor:
                    texto_restante = linha_str[:match_valor.start()].strip()

                    # Trava do Fantasma: Remove sinais soltos (+ ou -) para testar se sobrou texto
                    texto_limpo_sinais = re.sub(r'^[+-]+', '', texto_restante).strip()

                    # Se não sobrou texto, é apenas um pedaço do subtotal que caiu numa linha isolada! Ignora!
                    if not texto_limpo_sinais:
                        continue

                    # Se chegou aqui, é uma transação válida. Fecha a anterior!
                    if transacao_atual:
                        self._fechar_transacao(transacao_atual, registros)

                    valor_str = match_valor.group(1)
                    val_clean = self.limpar_valor(valor_str)

                    if val_clean > 0:
                        transacao_atual = {
                            "DATA": data_atual,
                            "HISTORICO": texto_restante,
                            # A direção (+ ou -) é ditada EXCLUSIVAMENTE pelo Bloco atual!
                            "VALOR": -abs(val_clean) if modo_atual == "DEBITO" else abs(val_clean),
                            "TIPO": modo_atual
                        }
                else:
                    # Não tem valor no fim da linha? É continuação do Histórico!
                    if transacao_atual:
                        transacao_atual["HISTORICO"] += " " + linha_str

            # Fim do documento: Fecha a última transação que ficou aberta
            if transacao_atual:
                self._fechar_transacao(transacao_atual, registros)

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar NUBANK {arquivo}: {e}", "erro")
            return None

    def _fechar_transacao(self, transacao_atual, registros):
        """
        Apenas higieniza o texto final. A matemática está 100% controlada pela regra de blocos!
        """
        hist_limpo = self.remover_acentos(transacao_atual["HISTORICO"]).upper()
        # Remove sinais de + ou - isolados e espaços extras
        hist_limpo = re.sub(r'^[+-]+', '', hist_limpo).strip()
        hist_limpo = re.sub(r'\s+', ' ', hist_limpo).strip(" -|.,")

        transacao_atual["HISTORICO"] = hist_limpo if hist_limpo else "HISTORICO NAO IDENTIFICADO"
        registros.append(transacao_atual)