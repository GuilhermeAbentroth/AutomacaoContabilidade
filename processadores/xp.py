import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class XPProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "XP"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo XP (Amputação Dinâmica e Memória Contínua): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            linhas = []

            # =========================================================
            # 1. AGRUPAMENTO COM GUILHOTINA DE RODAPÉ
            # =========================================================
            for page in doc:
                words = page.get_text("words")
                if not words: continue

                # Descobre dinamicamente a altura do Rodapé para o cortar
                y_corte_bottom = page.rect.height
                for w in words:
                    texto_w = w[4].upper()
                    # O rodapé gigante da XP começa com "IMPORTANTE:"
                    if "IMPORTANTE:" in texto_w or "OUVIDORIA" in texto_w:
                        y_corte_bottom = min(y_corte_bottom, w[1] - 5)

                words_uteis = [w for w in words if w[1] <= y_corte_bottom]
                if not words_uteis: continue

                words_uteis.sort(key=lambda w: (w[1], w[0]))

                linha_atual = []
                y_ref = None
                linhas_da_pagina = []

                for w in words_uteis:
                    if y_ref is None:
                        linha_atual.append(w)
                        y_ref = w[1]
                    elif abs(w[1] - y_ref) <= 4:
                        linha_atual.append(w)
                    else:
                        linha_atual.sort(key=lambda x: x[0])
                        linhas_da_pagina.append(" ".join([x[4] for x in linha_atual]))
                        linha_atual = [w]
                        y_ref = w[1]

                if linha_atual:
                    linha_atual.sort(key=lambda x: x[0])
                    linhas_da_pagina.append(" ".join([x[4] for x in linha_atual]))

                linhas.extend(linhas_da_pagina)

            if not linhas:
                log_func(f"Aviso: Nenhuma linha útil encontrada em {arquivo}", "erro")
                return None

            registros = []
            data_atual = None
            buffer_desc = ""

            # =========================================================
            # 2. MÁQUINA DE ESTADOS CONTÍNUA
            # =========================================================
            for linha in linhas:
                linha_str = linha.strip()
                if not linha_str: continue
                linha_up = linha_str.upper()

                # Lixo sistêmico da XP
                if "SALDO DISPONÍVEL" in linha_up or "SALDO DISPONIVEL" in linha_up: continue
                if "CONTA DIGITAL XP" in linha_up: continue
                if "DATA DA CONSULTA:" in linha_up: continue
                if "BANCO XP S.A" in linha_up: continue
                if "DOCUMENTO:" in linha_up: continue

                # =========================================================
                # PASSO 1: DATA (Ex: 23/11/25 às 17:34:13)
                # =========================================================
                match_data = re.search(r'\b(\d{2}/\d{2}/(\d{2}|\d{4}))\s+[AÀaà][Ss]\s+\d{2}:\d{2}:\d{2}\b', linha_str)
                if match_data:
                    data_raw = match_data.group(1)
                    partes = data_raw.split('/')
                    # Transforma o ano de 2 dígitos (25) em 4 dígitos (2025)
                    if len(partes[2]) == 2:
                        data_atual = f"{partes[0]}/{partes[1]}/20{partes[2]}"
                    else:
                        data_atual = data_raw

                    # Remove a data (e a hora) da linha
                    linha_str = linha_str[:match_data.start()] + linha_str[match_data.end():]
                    linha_str = linha_str.strip()

                # Se a linha só tinha o cabeçalho da tabela, ignora
                if "DESCRIÇÃO" in linha_str.upper() and "VALOR" in linha_str.upper() and "SALDO" in linha_str.upper():
                    continue

                if not data_atual or not linha_str:
                    continue

                # =========================================================
                # PASSO 2: CAPTURA DE VALORES E GRAVAÇÃO
                # =========================================================
                valores = re.findall(r'(-?\s*R\$\s*[-\u2010-\u2015\u2212]?\s*[\d\.,]+)', linha_str, re.IGNORECASE)

                if valores:
                    val_str_raw = valores[0]

                    texto_resto = linha_str
                    for v in valores:
                        texto_resto = texto_resto.replace(v, "")

                    if texto_resto.strip():
                        buffer_desc += " " + texto_resto.strip()

                    eh_negativo = "-" in val_str_raw or "\u2212" in val_str_raw
                    val_clean = self.limpar_valor(val_str_raw.replace("R$", "").replace("-", "").replace("\u2212", "").strip())

                    if val_clean > 0:
                        desc_final = buffer_desc.strip()
                        # Limpa aspas do Pix
                        desc_final = desc_final.replace('""', '').replace('"', '').strip()

                        if not desc_final:
                            desc_final = "HISTORICO NAO IDENTIFICADO"

                        registros.append({
                            "DATA": data_atual,
                            "HISTORICO": self.remover_acentos(desc_final).upper(),
                            "VALOR": -abs(val_clean) if eh_negativo else abs(val_clean),
                            "TIPO": "DEBITO" if eh_negativo else "CREDITO"
                        })

                    # Reseta a "memória" para o próximo lançamento
                    buffer_desc = ""
                else:
                    # Linha sem R$? É continuação da descrição
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
            log_func(f"Erro ao processar XP {arquivo}: {e}", "erro")
            return None