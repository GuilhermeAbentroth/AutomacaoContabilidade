import pandas as pd

# As colunas exatas para o padrão ABRASF / Betha Cloud
colunas = [
    "ID_RPS", "STATUS", "NUMERO_NOTA", "CNPJ_CPF", "RAZAO_SOCIAL",
    "EMAIL", "CEP", "ENDERECO", "NUMERO", "BAIRRO",
    "CODIGO_IBGE_CIDADE", "UF", "VALOR_SERVICO", "DISCRIMINACAO",
    "ITEM_LISTA_SERVICO", "CODIGO_CNAE", "CODIGO_TRIBUTACAO_MUNICIPIO", "ISS_RETIDO"
]

# Dados fictícios apenas para a linha 2 servir de exemplo
exemplo = [{
    "ID_RPS": 1,
    "STATUS": "",
    "NUMERO_NOTA": "",
    "CNPJ_CPF": "12345678000199",
    "RAZAO_SOCIAL": "Empresa Fictícia LTDA",
    "EMAIL": "contato@empresa.com.br",
    "CEP": "89251000",
    "ENDERECO": "Rua Marechal Deodoro da Fonseca",
    "NUMERO": "100",
    "BAIRRO": "Centro",
    "CODIGO_IBGE_CIDADE": "4208906",
    "UF": "SC",
    "VALOR_SERVICO": 1500.00,
    "DISCRIMINACAO": "Referente a honorarios contabeis do mes 04/2026",
    "ITEM_LISTA_SERVICO": "17.19",
    "CODIGO_CNAE": "6920601",
    "CODIGO_TRIBUTACAO_MUNICIPIO": "",
    "ISS_RETIDO": 2
}]

df = pd.DataFrame(exemplo, columns=colunas)

# Salva na mesma pasta onde o script rodar
df.to_excel("modelo_notas.xlsx", index=False)
print("Planilha 'modelo_notas.xlsx' gerada com sucesso!")