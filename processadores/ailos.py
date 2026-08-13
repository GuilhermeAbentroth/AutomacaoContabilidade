import os
import re
import pdfplumber
from base_processor import BaseProcessor


# ==========================================
# CLASSE 1: AILOS V1 (Padrão de Tabelas Antigo)
# ==========================================
class AilosProcessorV1(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "AILOS_V1"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo AILOS V1: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        dados_brutos = []

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    tabela = page.extract_table({
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text"
                    })
                    if tabela:
                        for linha in tabela:
                            if linha and any(linha):
                                dados_brutos.append(linha)

            if not dados_brutos:
                log_func(f"Aviso: Nenhuma tabela encontrada em {arquivo}", "erro")
                return None

            registros = []

            for linha in dados_brutos:
                cols = [str(x).strip() if x else "" for x in linha]
                if len(cols) < 5: continue

                val_data = cols[0]
                if not re.search(r'\d{2}/\d{2}/\d{4}', val_data):
                    continue

                val_deb = cols[-2]
                val_cred = cols[-3]

                itens_descricao = cols[1:-4]
                val_desc = " ".join(itens_descricao).strip()
                if not val_desc and len(cols) >= 5:
                    val_desc = " ".join(cols[1:-3]).strip()

                valor_final = 0.0
                tipo = ""

                if val_deb and re.search(r'[\d,]', val_deb):
                    v = self.limpar_valor(val_deb)
                    if v != 0:
                        valor_final = -abs(v)
                        tipo = "DEBITO"
                elif val_cred and re.search(r'[\d,]', val_cred):
                    v = self.limpar_valor(val_cred)
                    if v != 0:
                        valor_final = abs(v)
                        tipo = "CREDITO"

                if valor_final != 0:
                    registros.append({
                        "DATA": val_data,
                        "HISTORICO": self.remover_acentos(val_desc).upper(),
                        "VALOR": valor_final,
                        "TIPO": tipo
                    })

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_V1"
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Layout não reconhecido ou sem transações em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar V1 {arquivo}: {e}", "erro")
            return None


# ==========================================
# CLASSE 2: AILOS V2 (Extrato Especial Viacredi)
# ==========================================
class AilosProcessorV2(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "AILOS_V2"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo AILOS_V2: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        registros = []

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                stop_p = False
                transacao_atual = None

                for page in pdf.pages:
                    if stop_p: break
                    words = page.extract_words()
                    if not words: continue

                    # Agrupa as palavras linha a linha mantendo a tolerância Y
                    words.sort(key=lambda w: (round(w['top']), w['x0']))
                    linhas_words = []
                    linha_atual = []
                    y_ref = None

                    for w in words:
                        if y_ref is None:
                            linha_atual.append(w)
                            y_ref = w['top']
                        elif abs(w['top'] - y_ref) <= 3:
                            linha_atual.append(w)
                        else:
                            linha_atual.sort(key=lambda x: x['x0'])
                            linhas_words.append(linha_atual)
                            linha_atual = [w]
                            y_ref = w['top']
                    if linha_atual:
                        linha_atual.sort(key=lambda x: x['x0'])
                        linhas_words.append(linha_atual)

                    for lw in linhas_words:
                        txt_l = " ".join([w['text'] for w in lw]).strip()
                        if not txt_l: continue

                        txt_upper = txt_l.upper()

                        # 1. Ignorar lixo e cabeçalhos espalhados
                        lixo = [
                            "VIACREDI", "EXTRATO", "DESTINO:", "SEQ", "PA:", "JRG", "CONTA/DV:",
                            "TITULAR:", "LIMITE", "SALDO ANTERIOR", "JUROS", "DATA HISTORICO"
                        ]
                        if any(txt_upper.startswith(x) for x in lixo) or "DOCUMENTO LIBER" in txt_upper:
                            continue

                        # 2. Nova transação? (A Data na Viacredi vem como DD/MM/YY)
                        m_d = re.match(r'^(\d{2}/\d{2}/\d{2})\b', txt_l)

                        if m_d:
                            # Se encontrou nova data, finaliza e guarda a transação que estava aberta!
                            if transacao_atual and transacao_atual["VALOR"] is not None:
                                self._finalizar_transacao(transacao_atual, registros)

                            data_raw = m_d.group(1)
                            # Transforma "18/03/26" em "18/03/2026"
                            d_split = data_raw.split('/')
                            data_final = f"{d_split[0]}/{d_split[1]}/20{d_split[2]}"

                            transacao_atual = {
                                "DATA": data_final,
                                "HISTORICO_BRUTO": "",
                                "VALOR": None,
                                "TIPO": None
                            }
                            # Retira a data da frase
                            txt_l = txt_l.replace(data_raw, "", 1).strip()

                        if transacao_atual:
                            # 3. Extração do Valor
                            if transacao_atual["VALOR"] is None:
                                # O valor da transação na Viacredi tem sempre um D ou C colado a ele
                                matches_v = list(re.finditer(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*([DCdc])\b', txt_upper))
                                if matches_v:
                                    match_v = matches_v[-1]
                                    v_s = match_v.group(1)
                                    sufixo = match_v.group(2).upper()

                                    tipo = "DEBITO" if sufixo == 'D' else "CREDITO"
                                    val_limpo = self.limpar_valor(v_s)
                                    transacao_atual["VALOR"] = -abs(val_limpo) if tipo == "DEBITO" else abs(val_limpo)
                                    transacao_atual["TIPO"] = tipo

                                    # Arranca o valor da frase para não sujar o histórico
                                    padrao_remover = re.escape(v_s) + r'\s*[DdCc]\b'
                                    txt_l = re.sub(padrao_remover, "", txt_l, flags=re.IGNORECASE)

                            # 4. Adiciona o texto que sobrou na linha ao histórico
                            transacao_atual["HISTORICO_BRUTO"] += " " + txt_l

                # Finaliza a última transação lida no documento
                if transacao_atual and transacao_atual["VALOR"] is not None:
                    self._finalizar_transacao(transacao_atual, registros)

            # 5. Gravação
            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_V2"
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar AILOS V2 {arquivo}: {e}", "erro")
            return None


    def _finalizar_transacao(self, transacao, registros):
        """
        Função auxiliar para limpar o lixo de saldos e documentos do histórico.
        """
        desc = transacao["HISTORICO_BRUTO"]

        # Remove Saldos que sobraram na linha (valores como 10.151,21 que não tinham D/C)
        desc = re.sub(r'\b\d{1,3}(?:\.\d{3})*,\d{2}\b', '', desc)

        # Remove Documentos (Qualquer código numérico com 4 ou mais dígitos)
        desc = re.sub(r'\b\d{4,}\b', '', desc)

        # Remove Códigos pontuados tipo "1660.102"
        desc = re.sub(r'\b\d+\.\d+\b', '', desc)

        # Limpa espaços extras e hífens isolados
        desc = re.sub(r'\s+', ' ', desc).strip(" -|.,")
        desc = self.remover_acentos(desc).upper()

        if not desc:
            desc = "HISTORICO NAO IDENTIFICADO"

        registros.append({
            "DATA": transacao["DATA"],
            "HISTORICO": desc,
            "VALOR": transacao["VALOR"],
            "TIPO": transacao["TIPO"]
        })

        # Reseta o buffer para evitar vazamentos de memória (embora o objeto seja descartado de seguida)
        transacao["HISTORICO_BRUTO"] = ""


# ==========================================
# CLASSE 3: AILOS V3 (Extrato Conta Corrente Viacredi - Novo Layout)
# ==========================================
class AilosProcessorV3(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "AILOS_V3"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo AILOS_V3: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        registros = []

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                saldo_anterior = None

                for page in pdf.pages:
                    texto = page.extract_text()
                    if not texto:
                        continue

                    for linha in texto.split("\n"):
                        tokens = linha.split()
                        if len(tokens) < 3:
                            continue

                        if not re.match(r'^\d{2}/\d{2}/\d{4}$', tokens[0]):
                            continue

                        saldo_tok = tokens[-1]
                        valor_tok = tokens[-2]

                        if not re.match(r'^-?\d{1,3}(\.\d{3})*,\d{2}$', saldo_tok):
                            continue

                        saldo_atual = self.limpar_valor(saldo_tok)

                        # Linha "SALDO ANTERIOR": apenas ancora o saldo, não gera transação
                        if valor_tok == "-":
                            saldo_anterior = saldo_atual
                            continue

                        if not re.match(r'^\d{1,3}(\.\d{3})*,\d{2}$', valor_tok):
                            continue

                        valor_num = self.limpar_valor(valor_tok)
                        desc = " ".join(tokens[1:-2]).strip()

                        if saldo_anterior is None or valor_num == 0:
                            saldo_anterior = saldo_atual
                            continue

                        delta = round(saldo_atual - saldo_anterior, 2)
                        if delta < 0:
                            tipo = "DEBITO"
                            valor_final = -abs(valor_num)
                        else:
                            tipo = "CREDITO"
                            valor_final = abs(valor_num)

                        registros.append({
                            "DATA": tokens[0],
                            "HISTORICO": self.remover_acentos(desc).upper(),
                            "VALOR": valor_final,
                            "TIPO": tipo
                        })

                        saldo_anterior = saldo_atual

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_V3"
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar AILOS V3 {arquivo}: {e}", "erro")
            return None