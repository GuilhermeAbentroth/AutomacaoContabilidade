import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class CresolProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "CRESOL"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo Cresol (Modo Nativo de Blocos Textuais): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            linhas = []

            for page in doc:
                texto = page.get_text("text")
                linhas.extend(texto.split('\n'))

            if not linhas:
                log_func(f"Aviso: Nenhuma linha útil encontrada em {arquivo}", "erro")
                return None

            registros = []
            transacao_atual = None

            for linha in linhas:
                linha_str = linha.strip()
                if not linha_str: continue
                linha_up = linha_str.upper()

                # =========================================================
                # 1. A GUILHOTINA REFORÇADA (Ignora saldos e lixo)
                # =========================================================
                # Filtro mais agressivo para qualquer variação de Saldo
                if re.search(r"SALDO\s+(ANTERIOR|DO\s+DIA|EM\s+CONTA|DISPON|CONSOL|BLOQUEADO)", linha_up):
                    continue

                if "CONSULTA POSI" in linha_up: continue
                if "PERIODO DE" in linha_up or "PÁGINA" in linha_up or "PAGINA" in linha_up: continue
                if "LIMITE DE CR" in linha_up: continue
                if "LANÇAMENTOS" == linha_up or "LANCAMENTOS" == linha_up: continue
                if "CRESOL" == linha_up: continue
                if "AGÊNCIA" in linha_up or "AGENCIA " in linha_up: continue
                if re.match(r'^\d{2} DE [A-Z]+ DE \d{4}', linha_up): continue

                # =========================================================
                # 2. IDENTIFICA O INÍCIO DE UMA TRANSAÇÃO
                # =========================================================
                match_data = re.match(r'^(\d{2}/\d{2}/\d{4})', linha_str)

                if match_data:
                    # Se havia uma transação pendente, finaliza antes de abrir a nova
                    if transacao_atual:
                        finalizada = self._finalizar_transacao(transacao_atual)
                        if finalizada: registros.append(finalizada)

                    data_str = match_data.group(1)
                    resto = linha_str[10:].strip()

                    match_valor = re.search(r'([+-]?\s*(?:R\$|RS)?\s*\d{1,3}(?:\.\d{3})*,\d{2})$', resto, re.IGNORECASE)
                    valor_str = ""

                    if match_valor:
                        valor_str = match_valor.group(1)
                        resto = resto[:match_valor.start()].strip()

                    transacao_atual = {
                        "data": data_str,
                        "historico": resto,
                        "valor_str": valor_str
                    }

                    if valor_str:
                        finalizada = self._finalizar_transacao(transacao_atual)
                        if finalizada: registros.append(finalizada)
                        transacao_atual = None

                else:
                    # =========================================================
                    # 3. CONTINUAÇÃO DE HISTÓRICO
                    # =========================================================
                    if transacao_atual:
                        match_valor = re.search(r'([+-]?\s*(?:R\$|RS)?\s*\d{1,3}(?:\.\d{3})*,\d{2})$', linha_str,
                                                re.IGNORECASE)

                        if match_valor:
                            transacao_atual["valor_str"] = match_valor.group(1)
                            texto_extra = linha_str[:match_valor.start()].strip()
                            if texto_extra: transacao_atual["historico"] += " " + texto_extra

                            finalizada = self._finalizar_transacao(transacao_atual)
                            if finalizada: registros.append(finalizada)
                            transacao_atual = None
                        else:
                            transacao_atual["historico"] += " " + linha_str

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df, nome_base)

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro CRESOL {arquivo}: {e}", "erro")
            return None

    def _finalizar_transacao(self, transacao):
        """ Limpa a transação e aplica as regras financeiras """
        if not transacao.get("valor_str"): return None

        hist = transacao["historico"].upper()

        # --- FILTRO DE SEGURANÇA EXTRA ---
        # Se restou a palavra SALDO no histórico, ignoramos a transação inteira
        if "SALDO" in hist:
            return None

        val_str_raw = transacao["valor_str"].replace(" ", "")
        val_clean = self.limpar_valor(val_str_raw.replace("+", "").replace("-", "").replace("R$", "").replace("RS", ""))

        if val_clean == 0: return None

        eh_negativo = "-" in val_str_raw
        eh_positivo = "+" in val_str_raw

        # Remove os IDs gigantes
        hist = re.sub(r'\b\d{10,}\b', '', hist).strip()

        # Motor de reconhecimento de Débito/Crédito
        if "BLOQUEIO" in hist and "DESBLOQUEIO" not in hist:
            eh_negativo = True
        elif "DESBLOQUEIO" in hist:
            eh_negativo = False
        elif not eh_negativo and not eh_positivo:
            palavras_debito = ["DEBITO", "DÉBITO", "TARIFA", "CUSTAS", "PAGAMENTO", "SAQUE", "CHEQUE", "ENCARGO",
                               "CONSORCIO", "MENSALIDADE", "IMPOSTO", "IOF", "TED"]
            eh_negativo = any(p in hist for p in palavras_debito)

        tipo = "DEBITO" if eh_negativo else "CREDITO"
        valor_final = -abs(val_clean) if eh_negativo else abs(val_clean)

        historico_final = self.remover_acentos(hist).strip()
        historico_final = re.sub(r'^-\s*', '', historico_final)

        if not historico_final:
            return None  # Em vez de nomear como lançamento, descartamos se estiver vazio

        return {
            "DATA": transacao["data"],
            "HISTORICO": historico_final,
            "VALOR": valor_final,
            "TIPO": tipo
        }


# ==========================================
# CRESOL V2 (Extrato Consolidado de Conta Corrente)
# ==========================================
class CresolProcessorV2(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "CRESOL_V2"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo Cresol V2 (Extrato Consolidado): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        registros = []

        try:
            doc = fitz.open(caminho_pdf)

            for page in doc:
                words = page.get_text("words")
                if not words:
                    continue

                # Agrupa as palavras em linhas pela coordenada Y (o layout desta
                # tabela é montado por colunas fixas, não pela ordem do texto)
                words.sort(key=lambda w: (round(w[1]), w[0]))
                linhas_words = []
                linha_atual = []
                y_ref = None

                for w in words:
                    if y_ref is None or abs(w[1] - y_ref) <= 3:
                        linha_atual.append(w)
                        y_ref = w[1] if y_ref is None else y_ref
                    else:
                        linhas_words.append(linha_atual)
                        linha_atual = [w]
                        y_ref = w[1]
                if linha_atual:
                    linhas_words.append(linha_atual)

                for lw in linhas_words:
                    lw.sort(key=lambda w: w[0])

                    # Colunas fixas da tabela: Data Movimento | Lançamento | Identificação | Valor
                    col_data = [w[4] for w in lw if w[0] < 95]
                    col_lanc = [w[4] for w in lw if 95 <= w[0] < 335]
                    col_ident = [w[4] for w in lw if 335 <= w[0] < 520]
                    col_valor = [w[4] for w in lw if w[0] >= 520]

                    data_txt = " ".join(col_data).strip()
                    if not re.match(r'^\d{2}/\d{2}/\d{4}$', data_txt):
                        continue

                    valor_txt = " ".join(col_valor).strip()
                    match_valor = re.match(r'^(\d{1,3}(?:\.\d{3})*,\d{2})\s*([DC])$', valor_txt)
                    if not match_valor:
                        continue

                    lanc_txt = " ".join(col_lanc).strip()

                    # Linha de "Saldo Anterior": apenas ancora o saldo do dia, não é transação
                    if re.match(r'^SALDO\s+ANTERIOR$', lanc_txt, re.IGNORECASE):
                        continue

                    ident_txt = " ".join(col_ident).strip()
                    historico = (lanc_txt + " " + ident_txt).strip()
                    historico = re.sub(r'\s+', ' ', historico)

                    valor_num = self.limpar_valor(match_valor.group(1))
                    tipo = "DEBITO" if match_valor.group(2) == "D" else "CREDITO"
                    valor_final = -abs(valor_num) if tipo == "DEBITO" else abs(valor_num)

                    if valor_num == 0 or not historico:
                        continue

                    registros.append({
                        "DATA": data_txt,
                        "HISTORICO": self.remover_acentos(historico).upper(),
                        "VALOR": valor_final,
                        "TIPO": tipo
                    })

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_V2"
                    return self.salvar_arquivo(df, nome_base)

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro CRESOL V2 {arquivo}: {e}", "erro")
            return None