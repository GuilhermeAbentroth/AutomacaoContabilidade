import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class StoneProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "STONE"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo STONE (Reconstrução Lógica Natural): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            texto_completo = ""

            # 1. Leitura de Texto Bruto (Idêntico ao CTRL+C / CTRL+V)
            for page in doc:
                texto_completo += page.get_text("text") + "\n"

            # Limpa quebras e formata numa lista sequencial
            linhas = [l.strip() for l in texto_completo.split('\n') if l.strip()]

            transacoes_puras = []
            buffer_transacao = []

            # Lixo estrutural a ignorar completamente (Cabeçalhos e Rodapés)
            lixo = [
                "EXTRATO", "EMITIDO", "STONE", "PÁGINA", "PAGINA", "PERÍODO", "PERIODO",
                "DOCUMENTO", "AGÊNCIA", "AGENCIA", "CONTA", "DATA", "SALDO", "CONTRAPARTE", "VALOR",
                "INSTITUIÇÃO", "NOME", "TIPO", "DESCRIÇÃO", "DESCRICAO", "EXTRATO DE CONTA CORRENTE",
                "DADOS DA CONTA"
            ]

            # 2. Agrupamento Sequencial das Transações
            for linha in linhas:
                linha_up = linha.upper()

                if any(linha_up.startswith(x) for x in lixo):
                    continue
                if "STONE INSTITUIÇÃO DE PAGAMENTO S.A." in linha_up:
                    continue
                if re.match(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$', linha):  # Ignora CNPJ solto
                    continue
                if re.match(r'^PERÍODO:.*', linha_up):
                    continue

                # Se encontrar uma data (Ex: 02/12/25), fecha a transação anterior e começa uma nova!
                if re.match(r'^\d{2}/\d{2}/\d{2,4}$', linha):
                    if buffer_transacao:
                        transacoes_puras.append(" ".join(buffer_transacao))
                    buffer_transacao = [linha]
                elif buffer_transacao:
                    buffer_transacao.append(linha)

            # Guarda a última transação lida
            if buffer_transacao:
                transacoes_puras.append(" ".join(buffer_transacao))

            if not transacoes_puras:
                log_func(f"Aviso: Nenhuma transação encontrada em {arquivo}", "erro")
                return None

            registros = []
            regex_valor = re.compile(r'([-\u2010-\u2015\u2212]?\s*R\$\s*[\d\.,]+)')

            # Lista de Operações para estruturar a frase final (em ordem de prioridade)
            operacoes_conhecidas = [
                "TRANSFERÊNCIA PIX", "TRANSFERENCIA PIX", "PIX | MAQUININHA", "PIX MAQUININHA",
                "RECEBIMENTO VENDAS", "PAGAMENTO DE BOLETO", "PAGAMENTO",
                "ANTECIPAÇÃO", "ANTECIPACAO", "DEVOLUÇÃO", "DEVOLUCAO",
                "TED", "DOC", "PIX"
            ]

            # 3. Processamento e Limpeza (Onde a mágica do Corte ocorre)
            for item in transacoes_puras:
                match_data = re.search(r'^(\d{2}/\d{2}/\d{2,4})', item)
                if not match_data: continue
                data_raw = match_data.group(1)

                valores = regex_valor.findall(item)
                if not valores: continue

                # Define o Tipo (Crédito ou Débito)
                tipo_mov = "CREDITO"
                eh_saida = False
                if re.search(r'\b(Saída|Saida|Tarifa|Devolução|Devolucao)\b', item, re.IGNORECASE):
                    tipo_mov = "DEBITO"
                    eh_saida = True
                else:
                    for v in valores:
                        if "-" in v or "\u2212" in v:
                            tipo_mov = "DEBITO"
                            eh_saida = True
                            break

                # Captura do Valor Correto (Para o Excel)
                val_str_raw = None
                if eh_saida:
                    for v in valores:
                        if "-" in v or "\u2212" in v:
                            val_str_raw = v
                            break
                    if not val_str_raw: val_str_raw = valores[0]
                else:
                    val_str_raw = valores[0]

                # =========================================================================
                # O CORTE DO SALDO/CONTRAPARTE: Isola o histórico descartando o resto
                # =========================================================================
                match_r = re.search(r'[-\u2010-\u2015\u2212]?\s*R\$', item)
                if match_r:
                    # Corta a string no exato momento antes do primeiro R$
                    historico_bruto = item[:match_r.start()]
                else:
                    historico_bruto = item

                # Limpeza Inicial da Descrição
                desc = historico_bruto.replace(data_raw, "")
                desc = re.sub(r'\b(Entrada|Saída|Saida)\b', '', desc, flags=re.IGNORECASE)
                desc = re.sub(r'\d{2}:\d{2}:\d{2}', '', desc)  # Limpa horas perdidas
                desc_upper = re.sub(r'\s+', ' ', desc).strip(" -|.,").upper()

                # =========================================================================
                # ESTRUTURAÇÃO DO HISTÓRICO: Puxa a Operação para o início e junta o Nome
                # =========================================================================
                if "TARIFA" in desc_upper:
                    desc_final = "TARIFA"
                else:
                    op_encontrada = ""
                    for op in operacoes_conhecidas:
                        if op in desc_upper:
                            op_encontrada = op
                            # Arranca a operação do meio para sobrar apenas o Nome
                            desc_upper = desc_upper.replace(op, "").strip(" -|.,")
                            break

                    corpo = desc_upper

                    # Elimina as repetições de nomes deixadas pela Stone (Ex: VIVO VIVO)
                    tokens = [t for t in corpo.split() if t.strip()]
                    if len(tokens) >= 4:
                        mid = len(tokens) // 2
                        if " ".join(tokens[:mid]) == " ".join(tokens[mid:]):
                            corpo = " ".join(tokens[:mid])
                    elif len(tokens) >= 2 and len(tokens) % 2 == 0:
                        mid = len(tokens) // 2
                        if " ".join(tokens[:mid]) == " ".join(tokens[mid:]):
                            corpo = " ".join(tokens[:mid])

                    # Montagem Final: (Ex: "PIX | MAQUININHA BRUNO MOURA HERNANDEZ")
                    if op_encontrada:
                        desc_final = f"{op_encontrada} {corpo}".strip()
                    else:
                        desc_final = corpo if corpo else "HISTORICO NAO IDENTIFICADO"

                # Processamento final dos valores monetários
                val_norm = re.sub(r'[-\u2010-\u2015\u2212]', '-', val_str_raw)
                v_num = self.limpar_valor(val_norm)
                valor_final = -abs(v_num) if tipo_mov == "DEBITO" else abs(v_num)

                # Ajuste para garantir Data com 4 dígitos no Ano
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