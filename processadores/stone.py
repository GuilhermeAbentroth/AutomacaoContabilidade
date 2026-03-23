import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class StoneProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "STONE"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo STONE (Fatiamento Inteligente com Regex Avançada): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            transacoes_puras = []

            for page in doc:
                words = page.get_text("words")
                if not words: continue

                # 1. Encontrar as "Âncoras" (Datas na margem esquerda que iniciam transações)
                anchors = []
                for w in words:
                    x0, y0, x1, y1, text = w[:5]
                    # Data tem de estar colada à esquerda (x0 < 100)
                    if x0 < 100 and re.match(r'^\d{2}/\d{2}/\d{2,4}$', text):
                        anchors.append(y0)

                anchors.sort()

                # Remove âncoras duplicadas para evitar bugs na mesma linha
                anchors_limpas = []
                for a in anchors:
                    if not anchors_limpas or (a - anchors_limpas[-1] > 10):
                        anchors_limpas.append(a)
                anchors = anchors_limpas

                if not anchors:
                    continue

                # 2. Fatiar a página em Blocos/Transações
                for i in range(len(anchors)):
                    y_start = anchors[i] - 5
                    y_end = anchors[i + 1] - 5 if i + 1 < len(anchors) else page.rect.height

                    valid_words = []
                    for w in words:
                        x0, y0, x1, y1, text = w[:5]
                        if not (y_start <= y0 < y_end):
                            continue

                        # Limpa ruído do PDF (Cabeçalhos e Rodapés que invadem a banda)
                        t_upper = text.upper()
                        if t_upper in ["EXTRATO", "EMITIDO", "STONE", "PÁGINA", "PAGINA", "PERÍODO", "PERIODO",
                                       "DOCUMENTO", "AGÊNCIA", "AGENCIA", "CONTA", "DATA", "TIPO", "DESCRIÇÃO",
                                       "DESCRICAO", "SALDO", "VALOR", "CONTRAPARTE", "INSTITUIÇÃO", "NOME"]:
                            continue

                        # Ignora o CNPJ solto
                        if re.match(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$', text):
                            continue

                        valid_words.append(w)

                    if not valid_words:
                        continue

                    # 3. Ordena palavras usando tolerância Y (evita cortes no meio da linha)
                    valid_words.sort(key=lambda w: (w[1], w[0]))

                    linhas_banda = []
                    linha_atual = []
                    y_ref = None

                    for w in valid_words:
                        if y_ref is None:
                            linha_atual.append(w)
                            y_ref = w[1]
                        elif abs(w[1] - y_ref) <= 4:
                            linha_atual.append(w)
                        else:
                            linha_atual.sort(key=lambda x: x[0])
                            linhas_banda.append(" ".join([x[4] for x in linha_atual]))
                            linha_atual = [w]
                            y_ref = w[1]

                    if linha_atual:
                        linha_atual.sort(key=lambda x: x[0])
                        linhas_banda.append(" ".join([x[4] for x in linha_atual]))

                    # Juntar com quebra de linha real para manter Operação e Nome separados!
                    texto_transacao = " \n ".join(linhas_banda).strip()
                    if texto_transacao:
                        transacoes_puras.append(texto_transacao)

            if not transacoes_puras:
                log_func(f"Aviso: Nenhuma transação encontrada em {arquivo}", "erro")
                return None

            registros = []
            regex_valor = re.compile(r'([-\u2010-\u2015\u2212]?\s*R\$\s*[\d\.,]+)')

            # Lista base para a sua Regra #2 (Puxar a operação para o início)
            operacoes_conhecidas = [
                "TRANSFERÊNCIA PIX", "TRANSFERENCIA PIX", "PIX MAQUININHA",
                "RECEBIMENTO VENDAS", "PAGAMENTO DE BOLETO", "PAGAMENTO",
                "ANTECIPAÇÃO", "ANTECIPACAO", "DEVOLUÇÃO", "DEVOLUCAO",
                "TARIFA", "TED", "DOC", "PIX"
            ]

            # 4. Extração e Limpeza Final
            for item in transacoes_puras:
                linhas_item = [l.strip() for l in item.split('\n') if l.strip()]
                texto_plano = " ".join(linhas_item)

                match_data = re.search(r'^(\d{2}/\d{2}/\d{2,4})', texto_plano)
                if not match_data: continue
                data_raw = match_data.group(1)

                valores = regex_valor.findall(texto_plano)
                if not valores: continue

                tipo_mov = "CREDITO"
                eh_saida = False

                # Identifica se é Débito (Saída)
                if re.search(r'\b(Saída|Saida|Tarifa|Devolução|Devolucao)\b', texto_plano, re.IGNORECASE):
                    tipo_mov = "DEBITO"
                    eh_saida = True
                else:
                    for v in valores:
                        if "-" in v or "\u2212" in v:
                            tipo_mov = "DEBITO"
                            eh_saida = True
                            break

                val_str_raw = None
                if eh_saida:
                    for v in valores:
                        if "-" in v or "\u2212" in v:
                            val_str_raw = v
                            break
                    if not val_str_raw: val_str_raw = valores[0]
                else:
                    val_str_raw = valores[0]

                # ==============================================================
                # Regras 1 e 2: Limpar a Data, Tipo e Valores do Histórico
                # ==============================================================
                linhas_limpas = []
                for linha in linhas_item:
                    l = linha
                    l = l.replace(data_raw, "")
                    for v in valores:
                        l = l.replace(v, "")
                    l = re.sub(r'\b(Entrada|Saída|Saida)\b', '', l, flags=re.IGNORECASE)
                    l = re.sub(r'\d{2}:\d{2}:\d{2}', '', l)
                    l = re.sub(r'\s+', ' ', l).strip(" -–—.|,")
                    if l:
                        linhas_limpas.append(l.upper())

                operacao_encontrada = ""
                outros_textos = []

                # Procura a Operação, salva, e remove-a para sobrar só a Empresa
                for l in linhas_limpas:
                    linha_eh_operacao = False
                    for op in operacoes_conhecidas:
                        if op in l:
                            operacao_encontrada = op
                            rem_l = l.replace(op, "").strip(" -|.,")
                            if rem_l:
                                outros_textos.append(rem_l)
                            linha_eh_operacao = True
                            break
                    if not linha_eh_operacao:
                        outros_textos.append(l)

                corpo = " ".join(outros_textos).strip()

                # Ignorar a coluna CONTRAPARTE (Elimina duplicações exatas como "C FERRARIO C FERRARIO")
                tokens = [t for t in corpo.split() if t.strip()]
                if len(tokens) >= 4:
                    mid = len(tokens) // 2
                    if " ".join(tokens[:mid]) == " ".join(tokens[mid:]):
                        corpo = " ".join(tokens[:mid])
                elif len(tokens) >= 2 and len(tokens) % 2 == 0:
                    mid = len(tokens) // 2
                    if " ".join(tokens[:mid]) == " ".join(tokens[mid:]):
                        corpo = " ".join(tokens[:mid])

                # ==============================================================
                # Regra 3: Formatação Final (Tarifa Exclusiva / Inversão Nome)
                # ==============================================================
                if "TARIFA" in operacao_encontrada or "TARIFA" in corpo:
                    desc_final = "TARIFA"
                elif "MAQUININHA" in corpo and not eh_saida:
                    desc_final = "PIX | MAQUININHA"
                elif ("ANTECIPAÇÃO" in corpo or "RECEBIMENTO VENDAS" in corpo) and not eh_saida:
                    desc_final = "ANTECIPAÇÃO | CRÉDITO"
                else:
                    if operacao_encontrada:
                        # Regra que pediu: Inicia com Operação (Pagamento) e junta o Nome (C FERRARIO)
                        desc_final = f"{operacao_encontrada} {corpo}".strip()
                    else:
                        desc_final = corpo if corpo else "HISTORICO NAO IDENTIFICADO"

                # Gravação e Processamento de Valor
                val_norm = re.sub(r'[-\u2010-\u2015\u2212]', '-', val_str_raw)
                v_num = self.limpar_valor(val_norm)
                valor_final = -abs(v_num) if tipo_mov == "DEBITO" else abs(v_num)

                data_final = data_raw
                if len(data_raw) == 8:
                    data_final = data_raw[:6] + "20" + data_raw[6:]

                registros.append({
                    "DATA": data_final,
                    "HISTORICO": self.remover_acentos(desc_final).upper(),
                    "VALOR": valor_final,
                    "TIPO": tipo_mov
                })

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar STONE {arquivo}: {e}", "erro")
            return None