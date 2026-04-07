import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class MercadoPagoProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "MERCADOPAGO"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo MERCADO PAGO (Leitura Contínua Padrão Stone): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            texto_completo = ""

            # 1. Leitura de Texto Bruto (Igual ao CTRL+C / CTRL+V da Stone)
            for page in doc:
                texto_completo += page.get_text("text") + "\n"

            # Limpa quebras e formata numa lista sequencial
            linhas = [l.strip() for l in texto_completo.split('\n') if l.strip()]

            transacoes_puras = []
            buffer_transacao = []

            # Lixo estrutural a ignorar completamente (Cabeçalhos e Rodapés)
            lixo = [
                "EXTRATO DE CONTA", "MERCADO PAGO", "SALDO INICIAL", "SALDO FINAL",
                "ENTRADAS:", "SAÍDAS:", "SAIDAS:", "DETALHE DOS MOVIMENTOS",
                "DATA", "DESCRIÇÃO", "DESCRICAO", "OPERAÇÃO", "OPERACAO", "VALOR", "SALDO",
                "CPF/CNPJ:", "PERIODO:", "PERÍODO:", "ID DA"
            ]

            # 2. Agrupamento Sequencial das Transações
            for linha in linhas:
                linha_up = linha.upper()

                # Bloqueia lixo indesejado
                if any(linha_up.startswith(x) for x in lixo):
                    continue
                # Corta a numeração de páginas que atrapalhava as descrições
                if "PÁGINA" in linha_up or "PAGINA" in linha_up:
                    continue
                # Ignora o CNPJ do cabeçalho
                if re.match(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', linha):
                    continue

                # Se encontrar uma data (Ex: 28-10-2025), fecha a transação anterior e começa uma nova!
                if re.match(r'^\d{2}-\d{2}-\d{4}', linha):
                    if buffer_transacao:
                        transacoes_puras.append(" ".join(buffer_transacao))
                    buffer_transacao = [linha]
                elif buffer_transacao:
                    # Tudo o que não é data e não é lixo, faz parte da descrição multilinha da transação atual
                    buffer_transacao.append(linha)

            # Guarda a última transação lida
            if buffer_transacao:
                transacoes_puras.append(" ".join(buffer_transacao))

            if not transacoes_puras:
                log_func(f"Aviso: Nenhuma transação encontrada em {arquivo}", "erro")
                return None

            registros = []
            # Regex preparada para apanhar "R$ 10,00" ou "- R$ 10,00"
            regex_valor = re.compile(r'([-\u2010-\u2015\u2212]?\s*R\$\s*[\d\.,]+)')

            # 3. Processamento e Limpeza (A Mágica do Corte Mestre)
            for item in transacoes_puras:
                match_data = re.search(r'^(\d{2}-\d{2}-\d{4})', item)
                if not match_data: continue

                data_raw = match_data.group(1)
                # Converte o padrão do MP (DD-MM-YYYY) para o oficial (DD/MM/YYYY)
                data_final = data_raw.replace("-", "/")

                # Localiza onde está o primeiro "R$" (podendo ter o sinal de menos atrás)
                match_r = re.search(r'[-\u2010-\u2015\u2212]?\s*R\$', item)
                if not match_r: continue

                # Extrai apenas os valores financeiros a partir do corte
                valores = regex_valor.findall(item[match_r.start():])
                if not valores: continue

                # Captura o primeiro valor encontrado (é sempre o da transação, o último é o saldo)
                val_str_raw = valores[0]

                # Regra Absoluta do Mercado Pago: Tem sinal de menos? É Saída. Não tem? É Entrada.
                eh_negativo = "-" in val_str_raw or "\u2212" in val_str_raw

                val_clean = self.limpar_valor(
                    val_str_raw.replace("R$", "").replace("-", "").replace("\u2212", "").strip())
                if val_clean == 0: continue

                tipo = "DEBITO" if eh_negativo else "CREDITO"
                valor_final = -abs(val_clean) if eh_negativo else abs(val_clean)

                # =========================================================================
                # O CORTE MESTRE: Isola o histórico descartando a direita (Valores/Saldo)
                # =========================================================================
                historico_bruto = item[:match_r.start()]

                # Limpeza Inicial da Descrição
                desc = historico_bruto.replace(data_raw, "")

                # Remove o ID da operação gigante (que varia de 10 a 30 números)
                desc = re.sub(r'\b\d{10,30}\b', '', desc)

                # Remove espaços duplicados e limpa pontuações nas bordas
                desc = re.sub(r'\s+', ' ', desc).strip(" -|.,")

                if not desc:
                    desc = "HISTORICO NAO IDENTIFICADO"

                registros.append({
                    "DATA": data_final,
                    "HISTORICO": self.remover_acentos(desc).upper(),
                    "VALOR": valor_final,
                    "TIPO": tipo
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
            log_func(f"Erro ao processar MERCADO PAGO {arquivo}: {e}", "erro")
            return None