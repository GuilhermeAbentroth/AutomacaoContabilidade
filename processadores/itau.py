import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class ItauProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "ITAU"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo Itaú (Lógica de Estado Restrita): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            registros = []
            transacao_atual = None
            # Texto de descrição que aparece ANTES da data quando uma linha
            # quebra entre páginas logo após um marcador de saldo (ver item 2b)
            buffer_pendente = ""
            apos_saldo = False

            for page in doc:
                linhas = page.get_text("text").split('\n')

                for linha in linhas:
                    linha_str = linha.strip()
                    if not linha_str: continue
                    linha_up = linha_str.upper()

                    # =========================================================
                    # 1. GUILHOTINA DE CABEÇALHO E SALDOS (FILTRO RÍGIDO)
                    # =========================================================
                    if linha_up in ["ITAÚ", "ITAU", "DATA", "LANÇAMENTOS", "VALOR (R$)", "SALDO (R$)", "RAZÃO SOCIAL",
                                    "CNPJ/CPF"]: continue
                    if "EXTRATO" in linha_up: continue
                    if "UTILIZADO" in linha_up: continue
                    if "AGÊNCIA" in linha_up: continue
                    if "PERÍODO:" in linha_up or "PERIODO:" in linha_up: continue

                    if "SALDO ANTERIOR" in linha_up or "SALDO TOTAL DISPONÍVEL" in linha_up or "SALDO TOTAL DISPONIVEL" in linha_up:
                        # Descarta a transação corrente na hora: ela é só o marcador de
                        # saldo (diário/anterior), não um lançamento real. Se deixássemos
                        # ela "aberta", o valor do saldo e/ou a descrição do PRÓXIMO
                        # lançamento (quando a linha quebra entre páginas) acabam sendo
                        # atribuídos a ela por engano, criando um lançamento fantasma.
                        transacao_atual = None
                        apos_saldo = True
                        continue

                    # =========================================================
                    # 2. DETECÇÃO DE NOVA DATA (FECHA A ANTERIOR E ABRE NOVA)
                    # =========================================================
                    match_data = re.match(r'^(\d{2}/\d{2}/\d{4})(.*)', linha_str)

                    if match_data:
                        # Se já tínhamos uma transação, tentamos salvar antes de resetar
                        if transacao_atual:
                            valida = self._finalizar_e_validar(transacao_atual)
                            if valida: registros.append(valida)

                        data_encontrada = match_data.group(1)
                        resto = match_data.group(2).strip()

                        # 2b. Se logo antes veio um marcador de saldo e sobrou texto de
                        # descrição "órfão" (a data ficou para a página seguinte), esse
                        # texto pertence a ESTE lançamento — prefixa o histórico com ele.
                        historico_inicial = resto if resto else ""
                        if buffer_pendente:
                            separator = " " if historico_inicial else ""
                            historico_inicial = buffer_pendente + separator + historico_inicial

                        transacao_atual = {
                            "data": data_encontrada,
                            "historico": historico_inicial,
                            "valor_str": None,
                            "tem_saldo_dia": False  # Marcador para evitar lixo
                        }
                        buffer_pendente = ""
                        apos_saldo = False
                        continue

                    # =========================================================
                    # 3. CAPTURA DE VALORES E HISTÓRICO ADICIONAL
                    # =========================================================
                    if transacao_atual:
                        # Procuramos o valor (padrão 1.234,56 ou -1.234,56)
                        match_valor = re.match(r'^-?[\d\.]*,\d{2}$', linha_str)

                        if match_valor:
                            # No Itaú, o primeiro valor após a data é a transação. O segundo é o saldo.
                            if not transacao_atual["valor_str"]:
                                transacao_atual["valor_str"] = linha_str
                            else:
                                # Se já temos valor, o que vier agora é o saldo do dia, ignoramos.
                                pass
                        else:
                            # Se não é valor nem data, é continuação do nome/descrição
                            # Limpa CNPJ/CPF no caminho
                            l = re.sub(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', '', linha_str)
                            l = re.sub(r'\d{3}\.\d{3}\.\d{3}-\d{2}', '', l).strip()

                            if l:
                                separator = " " if transacao_atual["historico"] else ""
                                transacao_atual["historico"] += separator + l
                    elif apos_saldo:
                        # Nenhuma transação aberta (acabamos de descartar um marcador de
                        # saldo) mas já veio texto: é a descrição do próximo lançamento
                        # chegando antes da própria data (quebra de página). Guarda até
                        # a data aparecer.
                        match_valor = re.match(r'^-?[\d\.]*,\d{2}$', linha_str)
                        if not match_valor:
                            l = re.sub(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', '', linha_str)
                            l = re.sub(r'\d{3}\.\d{3}\.\d{3}-\d{2}', '', l).strip()
                            if l:
                                separator = " " if buffer_pendente else ""
                                buffer_pendente += separator + l

            # Salva a última do PDF
            if transacao_atual:
                valida = self._finalizar_e_validar(transacao_atual)
                if valida: registros.append(valida)

            # =========================================================
            # 4. REGRA FINAL: REMOVER ÚLTIMO LANÇAMENTO (SALDO DO PERÍODO)
            # =========================================================
            if registros:
                registros.pop()

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0])

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro Crítico Itaú {arquivo}: {e}", "erro")
            return None

    def _finalizar_e_validar(self, t):
        """Valida se a transação é real ou apenas um saldo perdido."""
        if not t["valor_str"]: return None

        hist = t["historico"].upper().strip()

        # Se o histórico for vazio ou contiver apenas palavras de saldo, descartamos
        if not hist or "SALDO TOTAL" in hist or "SALDO ANTERIOR" in hist:
            return None

        # Se o histórico for muito curto (ex: apenas um caractere órfão), descartamos
        if len(hist) < 3:
            return None

        val_clean = self.limpar_valor(t["valor_str"].replace("-", "").replace("+", ""))
        if val_clean == 0: return None

        eh_negativo = "-" in t["valor_str"]
        historico_final = self.remover_acentos(hist)

        return {
            "DATA": t["data"],
            "HISTORICO": historico_final,
            "VALOR": -abs(val_clean) if eh_negativo else abs(val_clean),
            "TIPO": "DEBITO" if eh_negativo else "CREDITO"
        }


# ==========================================
# CLASSE 2: ITAÚ V2 (Extrato Mensal / Aplicação Automática)
# ==========================================
class ItauProcessorV2(BaseProcessor):
    """
    Extrato "mensal" do Itaú (conta com Aplicação Automática Mais).
    Layout em colunas fixas: data | descrição | entradas R$ | saídas R$ | saldo R$.
    A data vem sem ano (DD/MM) e só é repetida na primeira linha de cada dia.
    """

    MESES = {
        "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
    }

    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "ITAU_V2"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo Itaú V2 (Extrato Mensal): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            import pdfplumber

            registros = []

            with pdfplumber.open(caminho_pdf) as pdf:
                texto_cab = pdf.pages[0].extract_text() or ""
                m_periodo = re.search(
                    r'\b(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\s+(\d{4})\b',
                    texto_cab, re.IGNORECASE
                )
                if not m_periodo:
                    log_func(f"Aviso: Não foi possível identificar o mês/ano do extrato em {arquivo}", "erro")
                    return None

                mes_stmt = self.MESES[m_periodo.group(1).lower()]
                ano_stmt = int(m_periodo.group(2))

                data_atual = None
                parar = False

                for page in pdf.pages:
                    if parar:
                        break

                    words = page.extract_words()
                    if not words:
                        continue

                    # Remove a coluna de siglas explicativas (lado esquerdo da 1ª página):
                    # fica próxima o bastante no eixo Y de linhas reais da tabela para se
                    # misturar com elas ao agrupar por tolerância de altura.
                    words = [w for w in words if w["x0"] >= 145]
                    if not words:
                        continue

                    # Agrupa palavras em linhas visuais (mesma tolerância usada no AILOS V2)
                    words.sort(key=lambda w: (round(w["top"]), w["x0"]))
                    linhas_words = []
                    linha_atual = []
                    y_ref = None
                    for w in words:
                        if y_ref is None or abs(w["top"] - y_ref) <= 3:
                            linha_atual.append(w)
                            if y_ref is None:
                                y_ref = w["top"]
                        else:
                            linha_atual.sort(key=lambda x: x["x0"])
                            linhas_words.append(linha_atual)
                            linha_atual = [w]
                            y_ref = w["top"]
                    if linha_atual:
                        linha_atual.sort(key=lambda x: x["x0"])
                        linhas_words.append(linha_atual)

                    for lw in linhas_words:
                        if parar:
                            break

                        # Classifica cada palavra pela posição X (colunas fixas da tabela)
                        data_tok, desc_tok, entrada_tok, saida_tok = [], [], [], []
                        for w in lw:
                            x0 = w["x0"]
                            if x0 < 200:
                                data_tok.append(w["text"])
                            elif x0 < 350:
                                desc_tok.append(w["text"])
                            elif x0 < 420:
                                entrada_tok.append(w["text"])
                            elif x0 < 510:
                                saida_tok.append(w["text"])
                            # x0 >= 510: coluna "saldo", apenas informativa — ignorada

                        desc = " ".join(desc_tok).strip()
                        desc_norm = self.remover_acentos(desc)  # já vem em upper

                        if not desc:
                            continue

                        # Fim da tabela de movimentação: a partir daqui vem o resumo de
                        # aplicações automáticas, com layout de colunas diferente
                        if desc_norm.startswith("TOTALIZADOR"):
                            parar = True
                            break

                        if desc_norm in ("DESCRICAO",):
                            continue

                        # Atualiza a data corrente (só vem na primeira linha do dia)
                        if data_tok:
                            m_data = re.match(r'^(\d{2})/(\d{2})$', " ".join(data_tok))
                            if m_data:
                                dia, mes_linha = m_data.group(1), int(m_data.group(2))
                                if mes_linha == mes_stmt:
                                    ano_linha = ano_stmt
                                else:
                                    # Linha referente ao mês anterior (ex.: "Saldo anterior")
                                    ano_linha = ano_stmt if mes_stmt != 1 else ano_stmt - 1
                                data_atual = f"{dia}/{mes_linha:02d}/{ano_linha}"

                        # Linhas de saldo são só informativas (SALDO APLIC AUT MAIS,
                        # Saldo anterior, Saldo final, Saldo em C/C) — não são lançamentos
                        if desc_norm.startswith("SALDO"):
                            continue

                        if not data_atual:
                            continue

                        valor_entrada = "".join(entrada_tok).strip()
                        valor_saida = "".join(saida_tok).strip()

                        valor_final, tipo = None, None
                        if valor_saida and re.match(r'^[\d.]+,\d{2}-$', valor_saida):
                            v = self.limpar_valor(valor_saida.rstrip("-"))
                            if v != 0:
                                valor_final, tipo = -abs(v), "DEBITO"
                        elif valor_entrada and re.match(r'^[\d.]+,\d{2}$', valor_entrada):
                            v = self.limpar_valor(valor_entrada)
                            if v != 0:
                                valor_final, tipo = abs(v), "CREDITO"

                        if valor_final is not None:
                            registros.append({
                                "DATA": data_atual,
                                "HISTORICO": desc_norm,
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
            log_func(f"Erro Crítico Itaú V2 {arquivo}: {e}", "erro")
            return None