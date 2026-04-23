import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class InfinitePayProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "INFINITE_PAY"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo InfinitePay (Correção de Filtros de Depósito): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            registros = []
            data_atual = None

            for page in doc:
                words = page.get_text("words")
                if not words: continue

                # Agrupa palavras por linha (coordenada Y) para manter a integridade da tabela
                linhas_dict = {}
                for w in words:
                    y = round(w[1] / 3) * 3
                    if y not in linhas_dict: linhas_dict[y] = []
                    linhas_dict[y].append(w)

                y_ordenados = sorted(linhas_dict.keys())

                for y in y_ordenados:
                    linha_words = sorted(linhas_dict[y], key=lambda x: x[0])
                    texto_linha = " ".join([w[4] for w in linha_words]).strip()
                    linha_up = texto_linha.upper()

                    # =========================================================
                    # 1. FILTROS DE LIXO (AGORA MAIS PRECISOS)
                    # =========================================================
                    # Ignoramos apenas se a linha FOR o título ou o cabeçalho fixo
                    if linha_up == "INFINITEPAY": continue
                    if "RELATORIO DE MOVIMENTACOES" in linha_up: continue
                    if "DATA HORA TIPO" in linha_up: continue
                    if "CENTRAL DE AJUDA" in linha_up: continue
                    if "PAGINA" in linha_up and " DE " in linha_up: continue

                    # Filtros de Resumo (Ignora apenas se for o bloco de totais)
                    if "SALDO FINAL DO PERIODO" in linha_up and "R$" in linha_up: continue
                    if "TOTAL DE ENTRADAS" in linha_up or "TOTAL DE SAIDAS" in linha_up: continue
                    if "SALDO INICIAL" in linha_up: continue

                    # =========================================================
                    # 2. CAPTURA DE DATA (PERSISTÊNCIA)
                    # =========================================================
                    match_data = re.search(r'(\d{2}/\d{2}/\d{4})', texto_linha)
                    if match_data:
                        data_atual = match_data.group(1)

                    # =========================================================
                    # 3. CAPTURA DE VALOR (BUSCA + OU - EM QUALQUER PARTE)
                    # =========================================================
                    # Captura valores como +794,16 ou -30,00
                    match_valor = re.search(r'([+-])\s?([\d\.]*,\d{2})', texto_linha)

                    if match_valor and data_atual:
                        sinal = match_valor.group(1)
                        valor_str = match_valor.group(2)

                        # Limpeza do histórico
                        hist = texto_linha
                        if match_data: hist = hist.replace(data_atual, "")
                        hist = re.sub(r'\d{2}:\d{2}', '', hist)  # Remove Hora
                        hist = hist.replace(match_valor.group(0), "").strip()

                        # Remove palavras duplicadas consecutivas (Pix Pix)
                        palavras = hist.split()
                        final_words = []
                        for p in palavras:
                            if not final_words or p.upper() != final_words[-1].upper():
                                final_words.append(p)

                        hist_final = " ".join(final_words).upper()
                        hist_final = re.sub(r'\s+', ' ', hist_final).strip()

                        if not hist_final: hist_final = "MOVIMENTACAO INFINITEPAY"

                        # Tratamento financeiro
                        val_clean = self.limpar_valor(valor_str)
                        if val_clean == 0: continue

                        valor_final = -abs(val_clean) if sinal == "-" else abs(val_clean)

                        registros.append({
                            "DATA": data_atual,
                            "HISTORICO": self.remover_acentos(hist_final),
                            "VALOR": valor_final,
                            "TIPO": "DEBITO" if sinal == "-" else "CREDITO"
                        })

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0])

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro InfinitePay {arquivo}: {e}", "erro")
            return None