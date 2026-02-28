import os
import re
import fitz
import tabula
import pandas as pd
from datetime import datetime
from base_processor import BaseProcessor


class C6Processor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_banco = "C6"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo C6 Bank: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            # 1. Extrair Ano Base do cabeçalho
            doc = fitz.open(caminho_pdf)
            texto_completo = ""
            for page in doc:
                texto_completo += page.get_text("text") + "\n"
            doc.close()

            ano_atual = str(datetime.now().year)
            match_ano = re.search(r'\d{2}/\d{2}/(\d{4})', texto_completo)
            if match_ano:
                ano_atual = match_ano.group(1)

            # 2. Extrair com Tabula (stream e guess ajustados para ler blocos de texto puros)
            lista_tabelas = tabula.read_pdf(
                caminho_pdf,
                pages='all',
                multiple_tables=True,
                pandas_options={'header': None},
                stream=True,
                guess=False
            )

            if not lista_tabelas:
                log_func(f"Aviso: Nenhuma tabela detectada em {arquivo}", "erro")
                return None

            registros = []

            # Formatador blindado contra RS, R$ e pontuações americanas
            def formatar_valor_c6(v_str):
                v_str = str(v_str).upper().replace("R$", "").replace("RS", "").replace(" ", "").strip()
                sinal = -1 if "-" in v_str else 1
                v_str = re.sub(r'[^\d\,\.]', '', v_str)

                if not v_str: return 0.0

                if len(v_str) > 3 and v_str[-3] in [',', '.']:
                    inteiros = v_str[:-3].replace('.', '').replace(',', '')
                    decimais = v_str[-2:]
                    return float(f"{inteiros}.{decimais}") * sinal
                else:
                    v_str = v_str.replace('.', '').replace(',', '')
                    return float(v_str) * sinal

            # 3. Lógica Resiliente de Achatamento de Linhas
            for df in lista_tabelas:
                for index, row in df.iterrows():
                    try:
                        # Achata a linha, removendo colunas vazias
                        cols = [str(x).strip() for x in row.values if
                                pd.notna(x) and str(x).strip() not in ("", "nan", "None")]
                        if len(cols) < 3:
                            continue

                        # Procura uma data DD/MM na coluna 0.
                        match_data = re.search(r'^([0-3]\d/[0-1]\d)', cols[0])

                        # Se não for uma data, ou se for um lixo de OCR (ex: 60/60), tenta a próxima coluna
                        if not match_data and len(cols) > 1:
                            match_data = re.search(r'^([0-3]\d/[0-1]\d)', cols[1])
                            if match_data:
                                cols.pop(0)  # Descarta o lixo

                        if not match_data:
                            continue  # Não tem data, descarta (ex: "Saldo do dia")

                        data_formatada = f"{match_data.group(1)}/{ano_atual}"

                        # Limpa a data do texto onde ela estava
                        cols[0] = cols[0].replace(match_data.group(1), '').strip()

                        # Se existir a segunda data (Data Contábil) aglutinada, limpa-a também
                        if cols and re.search(r'^([0-3]\d/[0-1]\d)', cols[0]):
                            cols[0] = re.sub(r'^([0-3]\d/[0-1]\d)', '', cols[0]).strip()

                        # Deita fora blocos que ficaram vazios após remover as datas
                        while cols and not cols[0]:
                            cols.pop(0)

                        if not cols:
                            continue

                        # Procura o Valor Monetário no fim do texto da última coluna
                        valor_bruto = ""
                        # Regex caça: sinal negativo, RS ou R$, espaços, dígitos e centavos obrigatórios
                        match_valor = re.search(r'(-?(?:R\$|RS)?\s*\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\s*$', cols[-1],
                                                re.IGNORECASE)

                        if match_valor:
                            valor_bruto = match_valor.group(1)
                            # Remove o valor da coluna para não o repetir na descrição
                            cols[-1] = cols[-1].replace(valor_bruto, '').strip()
                        else:
                            valor_bruto = cols[-1]
                            cols.pop()

                        # Limpa eventuais blocos vazios no final
                        while cols and not cols[-1]:
                            cols.pop()

                        valor_final = formatar_valor_c6(valor_bruto)

                        # Evita linhas onde o valor formatado falhou
                        if valor_final == 0:
                            continue

                        # O que sobrou nas colunas do meio é o Histórico
                        historico_bruto = " - ".join([c for c in cols if c])
                        if not historico_bruto:
                            historico_bruto = "Lançamento C6"

                        tipo_mov = "CREDITO" if valor_final >= 0 else "DEBITO"

                        registros.append({
                            "DATA": data_formatada,
                            "HISTORICO": self.remover_acentos(historico_bruto).upper(),
                            "VALOR": valor_final,
                            "TIPO": tipo_mov
                        })

                    except Exception:
                        continue

            # 4. Finaliza e Salva com o Maestro Base
            if registros:
                df_final = self.preparar_dataframe(registros)
                if df_final is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    ficheiro_salvo = self.salvar_arquivo(df_final, nome_base)
                    return ficheiro_salvo
            else:
                log_func(f"Aviso: Nenhuma transação capturada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar {arquivo}: {e}", "erro")
            return None