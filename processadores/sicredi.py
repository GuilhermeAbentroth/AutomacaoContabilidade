import os
import pandas as pd
import pdfplumber
from base_processor import BaseProcessor


class SicrediProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_banco = "SICREDI"

    def processar(self, arquivo, log_func):
        """
        Lê e extrai os dados de um único PDF do banco Sicredi.
        Retorna o nome do ficheiro Excel gerado ou None em caso de falha.
        """
        log_func(f"Lendo SICREDI: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            # 1. Extração de Tabelas (substituindo o antigo método isolado)
            dados_brutos = []
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    # Usamos a estratégia padrão ou texto (ajuste se a grade do Sicredi falhar)
                    tabela = page.extract_table()
                    if tabela:
                        for linha in tabela:
                            if linha and any(linha):
                                dados_brutos.append(linha)

            if not dados_brutos:
                log_func(f"Aviso: Nenhuma tabela encontrada em {arquivo}", "erro")
                return None

            # 2. Utiliza o Pandas para encontrar o cabeçalho dinamicamente
            df = pd.DataFrame(dados_brutos)
            header_idx = -1

            for idx, row in df.iterrows():
                # Transforma a linha numa lista de strings maiúsculas para verificar
                linha_txt = [str(x).upper() for x in row if x]
                if any("DATA" in x for x in linha_txt) and any("VALOR" in x for x in linha_txt):
                    # Define esta linha como o nome das colunas e limpa os acentos
                    novas_cols = []
                    for x in df.iloc[idx]:
                        nome_limpo = self.remover_acentos(str(x)).upper().strip() if x else f"COL_{len(novas_cols)}"
                        novas_cols.append(nome_limpo)

                    df.columns = novas_cols
                    header_idx = idx
                    break

            if header_idx == -1:
                log_func(f"Aviso: Cabeçalho 'DATA' e 'VALOR' não encontrado em {arquivo}", "erro")
                return None

            # Corta o DataFrame para apagar o lixo acima do cabeçalho
            df = df.iloc[header_idx + 1:].reset_index(drop=True)

            # 3. Identifica as colunas cruciais
            c_d = next((c for c in df.columns if 'DATA' in c), None)
            c_h = next((c for c in df.columns if 'DESCRICAO' in c or 'HISTORICO' in c), None)
            c_v = next((c for c in df.columns if 'VALOR' in c), None)

            if c_d and c_h and c_v:
                # Converte a coluna de data para o formato datetime do Pandas
                df['DATA_FIX'] = pd.to_datetime(df[c_d], dayfirst=True, errors='coerce')
                # Apaga as linhas onde a data é inválida (geralmente saldos de final de página ou lixo)
                df = df.dropna(subset=['DATA_FIX']).copy()

                registros = []

                # 4. Converte os dados filtrados para a nossa estrutura padronizada
                for _, row in df.iterrows():
                    v_num = self.limpar_valor(row[c_v])
                    if v_num == 0: continue

                    tipo = 'DEBITO' if v_num < 0 else 'CREDITO'
                    valor_final = -abs(v_num) if tipo == 'DEBITO' else abs(v_num)

                    registros.append({
                        "DATA": row['DATA_FIX'].strftime('%d/%m/%Y'),
                        "HISTORICO": self.remover_acentos(row[c_h]).upper(),
                        "VALOR": valor_final,
                        "TIPO": tipo
                    })

                # 5. Salva utilizando a estrutura Pai
                if registros:
                    df_final = self.preparar_dataframe(registros)
                    if df_final is not None:
                        nome_base = os.path.splitext(arquivo)[0]
                        return self.salvar_arquivo(df_final, nome_base)
                else:
                    log_func(f"Aviso: Nenhuma transação válida extraída em {arquivo}", "erro")
                    return None
            else:
                log_func(f"Aviso: Colunas essenciais falharam (DATA, HISTORICO, VALOR) em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar {arquivo}: {e}", "erro")
            return None