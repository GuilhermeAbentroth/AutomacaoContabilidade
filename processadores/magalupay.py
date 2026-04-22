import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class MagaluPayProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "MAGALUPAY"

    def processar(self, arquivo, log_func):
        log_func(f"A ler MagaluPay (Modo Nativo contínuo): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            linhas = []

            # =========================================================
            # 1. AGRUPAMENTO COM RECONSTRUÇÃO DE LINHAS (Y-AXIS)
            # =========================================================
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
                    elif abs(w[1] - y_ref) <= 4:
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
                log_func(f"Aviso: Nenhuma linha útil encontrada em {arquivo}", "erro")
                return None

            registros = []
            data_atual = None
            buffer_desc = ""

            # Dicionário para converter o mês em texto para número
            meses = {
                "jan": "01", "fev": "02", "mar": "03", "abr": "04",
                "mai": "05", "jun": "06", "jul": "07", "ago": "08",
                "set": "09", "out": "10", "nov": "11", "dez": "12"
            }

            # =========================================================
            # 2. MÁQUINA DE ESTADOS DO MAGALUPAY (CORRIGIDA)
            # =========================================================
            for linha in linhas:
                linha_str = linha.strip()
                if not linha_str: continue

                # PASSO 1: EXTRAIR A DATA PRIMEIRO! (Antes de qualquer corte)
                # Procura o padrão "04 fev 2026"
                match_data = re.search(r'\b(\d{2})\s+([a-zA-Z]{3})\s+(\d{4})\b', linha_str)
                if match_data:
                    dia = match_data.group(1)
                    mes_str = match_data.group(2).lower()
                    ano = match_data.group(3)

                    if mes_str in meses:
                        data_atual = f"{dia}/{meses[mes_str]}/{ano}"

                    # Remove apenas a data da string, mantendo o resto intacto
                    linha_str = linha_str[:match_data.start()] + linha_str[match_data.end():]
                    linha_str = linha_str.strip()

                # Se a linha ficou vazia (só tinha a data) ou se ainda não temos data, ignorar
                if not data_atual or not linha_str:
                    continue

                linha_up = linha_str.upper()

                # PASSO 2: A GUILHOTINA (Agora só corta o que sobrou, mantendo a data a salvo)
                if "TOTAL DE ENTRADAS" in linha_up: continue
                if "TOTAL DE SAÍDAS" in linha_up or "TOTAL DE SAIDAS" in linha_up: continue
                if "SALDO" in linha_up: continue
                if "VALORES EM R$" in linha_up: continue
                if "MOVIMENTAÇÕES" in linha_up or "MOVIMENTACOES" in linha_up: continue

                # PASSO 3: VALOR (R$ ou -R$)
                match_valor = re.search(r'(-?\s*R\$\s*[\d\.,]+)', linha_str, re.IGNORECASE)

                if match_valor:
                    val_str_raw = match_valor.group(1)
                    texto_resto = linha_str.replace(val_str_raw, "").strip()

                    if texto_resto:
                        buffer_desc += " " + texto_resto

                    desc_final = buffer_desc.strip()

                    # Evita falsos positivos
                    if desc_final:
                        eh_negativo = "-" in val_str_raw
                        val_clean = self.limpar_valor(val_str_raw.replace("R$", "").replace("-", "").strip())

                        if val_clean > 0:
                            registros.append({
                                "DATA": data_atual,
                                "HISTORICO": self.remover_acentos(desc_final).upper(),
                                "VALOR": -abs(val_clean) if eh_negativo else abs(val_clean),
                                "TIPO": "DEBITO" if eh_negativo else "CREDITO"
                            })

                    # Limpa a memória do histórico para a próxima transação
                    buffer_desc = ""
                else:
                    # Se não tem valor, é a continuação de um texto longo (histórico particionado)
                    buffer_desc += " " + linha_str

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar MAGALUPAY {arquivo}: {e}", "erro")
            return None