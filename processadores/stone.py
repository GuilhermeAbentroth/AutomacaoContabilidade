import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class StoneProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_banco = "STONE"

        # Cabeçalhos e rodapés para ignorar
        self.junk_start = [
            "EXTRATO", "EMITIDO", "PÁGINA", "STONE", "PERÍODO",
            "DOCUMENTO", "AGÊNCIA", "CONTA", "SALDO", "VALOR", "DESCRIÇÃO"
        ]

    def processar(self, arquivo, log_func):
        """
        Lê e extrai os dados de um PDF da Stone utilizando análise geométrica (coordenadas Y).
        Retorna o nome do ficheiro Excel gerado ou None em caso de falha.
        """
        log_func(f"Lendo STONE (Geométrico): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            transacoes_puras = []

            # 1. Leitura Geométrica
            for page in doc:
                words = page.get_text("words")
                # Ordena as palavras primeiro pelo eixo Y (linha) e depois pelo X (coluna)
                words.sort(key=lambda w: (round(w[1]), w[0]))

                linhas = {}
                for w in words:
                    y = round(w[1])
                    if y not in linhas:
                        linhas[y] = []
                    linhas[y].append(w[4])

                for y in sorted(linhas.keys()):
                    texto_linha = " ".join(linhas[y]).strip()

                    # Se começa com data, inicia nova transação
                    if re.match(r'^\d{2}/\d{2}/\d{2,4}', texto_linha):
                        transacoes_puras.append(texto_linha)
                    # Se for continuação de linha e não for cabeçalho
                    elif transacoes_puras and not any(texto_linha.upper().startswith(j) for j in self.junk_start):
                        if len(texto_linha) > 5:
                            transacoes_puras[-1] += " " + texto_linha

            if not transacoes_puras:
                log_func(f"Aviso: Nenhuma transação encontrada em {arquivo}", "erro")
                return None

            registros = []
            regex_valor = re.compile(r'([-\u2010-\u2015\u2212]?\s*R\$\s*[\d\.,]+)')

            # 2. Processamento das Transações
            for item in transacoes_puras:
                match_data = re.search(r'^(\d{2}/\d{2}/\d{2,4})', item)
                if not match_data: continue
                data_raw = match_data.group(1)

                valores = regex_valor.findall(item)
                if not valores: continue
                val_str_raw = valores[0]

                tipo_mov = "CREDITO"
                eh_saida = False
                if re.search(r'(Saída|Saida|Tarifa|Devolução)', item, re.IGNORECASE) or "-" in val_str_raw:
                    tipo_mov = "DEBITO"
                    eh_saida = True

                # Limpeza da Descrição (Subtração)
                desc = item.replace(data_raw, "")
                for v in valores:
                    desc = desc.replace(v, "")

                desc = re.sub(r'\b(Entrada|Saída|Saida|Transferência|Pix)\b', '', desc, flags=re.IGNORECASE)
                desc = re.sub(r'\d{2}:\d{2}:\d{2}', '', desc)
                desc = re.sub(r'\s+', ' ', desc).strip()
                desc_upper = desc.upper()

                # === Regras de Negócio ===
                if "TARIFA" in desc_upper:
                    desc_final = "TARIFA"
                elif "MAQUININHA" in desc_upper and not eh_saida:
                    desc_final = "PIX | MAQUININHA"
                elif ("ANTECIPAÇÃO" in desc_upper or "RECEBIMENTO VENDAS" in desc_upper) and not eh_saida:
                    desc_final = "ANTECIPAÇÃO | CRÉDITO"
                else:
                    corpo = desc_upper.strip(" -–—.|")

                    # Remove nomes de PF antes de MAQUININHA caso tenha sobrado algo
                    if "MAQUININHA" in corpo and not eh_saida:
                        desc_final = "PIX | MAQUININHA"
                    else:
                        # Inversão de Pagamento
                        if "PAGAMENTO" in corpo:
                            corpo = "PAGAMENTO " + corpo.replace("PAGAMENTO", "").strip()

                        # Limpa repetições de leitura (ex: "VIVO VIVO")
                        tokens = corpo.split()
                        if len(tokens) >= 4:
                            mid = len(tokens) // 2
                            if " ".join(tokens[:mid]) == " ".join(tokens[mid:]):
                                corpo = " ".join(tokens[:mid])

                        desc_final = corpo

                # 3. Processamento do Valor utilizando o método Pai
                val_norm = re.sub(r'[-\u2010-\u2015\u2212]', '-', val_str_raw)
                v_num = self.limpar_valor(val_norm)
                valor_final = -abs(v_num) if tipo_mov == "DEBITO" else abs(v_num)

                # Ajuste de Data (Ex: 31/01/26 -> 31/01/2026)
                data_final = data_raw
                if len(data_raw) == 8:
                    data_final = data_raw[:6] + "20" + data_raw[6:]

                registros.append({
                    "DATA": data_final,
                    "HISTORICO": self.remover_acentos(desc_final).upper(),
                    "VALOR": valor_final,
                    "TIPO": tipo_mov
                })

            # 4. Finalização e Gravação
            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar {arquivo}: {e}", "erro")
            return None