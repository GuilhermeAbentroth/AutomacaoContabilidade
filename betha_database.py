import sqlite3
import os

class BethaDatabase:
    def __init__(self, db_path):
        # Recebe o caminho dinâmico (local ou rede) vindo do arquivo de configuração do main.py
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.criar_tabelas()

    def criar_tabelas(self):
        """Cria a estrutura de tabelas relacionais com todas as tags fiscais do Excel."""
        # Tabela de Prestadores (Fornecedores / Emitentes)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS prestadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cnpj TEXT UNIQUE,
                im TEXT,
                nome TEXT,
                caminho_pfx TEXT,
                senha_pfx TEXT,
                cnae TEXT,
                cod_servico TEXT,
                item_lista TEXT,
                exigibilidade_iss TEXT,
                natureza_operacao TEXT,
                iss_retido TEXT,
                aliquota_iss TEXT
            )
        """)
        # Tabela de Tomadores (Clientes / Destinatários)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tomadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prestador_id INTEGER,
                cnpj_cpf TEXT,
                razao_social TEXT,
                cep TEXT,
                logradouro TEXT,
                numero TEXT,
                complemento TEXT,
                bairro TEXT,
                cidade TEXT,
                uf TEXT,
                email TEXT,
                UNIQUE(prestador_id, cnpj_cpf),
                FOREIGN KEY (prestador_id) REFERENCES prestadores(id)
            )
        """)
        self.conn.commit()

    # --- OPERAÇÕES DO PRESTADOR ---
    def salvar_prestador(self, d):
        """Insere ou atualiza os dados fiscais e de certificado do prestador forçando strings."""
        query = """
            INSERT OR REPLACE INTO prestadores 
            (cnpj, im, nome, caminho_pfx, senha_pfx, cnae, cod_servico, item_lista, exigibilidade_iss, natureza_operacao, iss_retido, aliquota_iss)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.cursor.execute(query, (
            str(d['cnpj']), str(d['im']), str(d['nome']), str(d['pfx']), str(d['senha']),
            str(d['cnae']), str(d['servico']), str(d['item']), str(d['exigibilidade']),
            str(d['natureza']), str(d['iss_retido']), str(d['aliquota'])
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def listar_prestadores(self):
        """Retorna o nome e CNPJ de todos os prestadores para alimentar o ComboBox."""
        self.cursor.execute("SELECT nome, cnpj FROM prestadores ORDER BY nome")
        return self.cursor.fetchall()

    def buscar_dados_prestador(self, cnpj):
        """Busca a configuração fiscal completa do prestador pelo CNPJ."""
        self.cursor.execute("SELECT * FROM prestadores WHERE cnpj = ?", (str(cnpj),))
        return self.cursor.fetchone()

    def atualizar_certificado(self, cnpj, novo_caminho, nova_senha):
        """Atualiza apenas os dados do certificado digital (para casos de vencimento)."""
        self.cursor.execute("""
            UPDATE prestadores SET caminho_pfx = ?, senha_pfx = ? WHERE cnpj = ?
        """, (str(novo_caminho), str(nova_senha), str(cnpj)))
        self.conn.commit()

    def excluir_prestador(self, cnpj):
        """Remove um prestador e faz a deleção em cascata de todos os tomadores vinculados."""
        self.cursor.execute("SELECT id FROM prestadores WHERE cnpj = ?", (str(cnpj),))
        res = self.cursor.fetchone()
        if res:
            prestador_id = res[0]
            self.cursor.execute("DELETE FROM tomadores WHERE prestador_id = ?", (prestador_id,))
            self.cursor.execute("DELETE FROM prestadores WHERE id = ?", (prestador_id,))
            self.conn.commit()

    # --- OPERAÇÕES DO TOMADOR ---
    def salvar_tomador(self, prestador_id, t):
        """Insere ou atualiza o cadastro do cliente (tomador) vinculado ao prestador forçando strings."""
        query = """
            INSERT OR REPLACE INTO tomadores 
            (prestador_id, cnpj_cpf, razao_social, cep, logradouro, numero, complemento, bairro, city, uf, email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Nota: Caso sua tabela use a coluna 'city' ou 'cidade', o mapeamento garante compatibilidade
        try:
            self.cursor.execute(query.replace("city", "cidade"), (
                prestador_id, str(t['cnpj_cpf']), str(t['razao_social']), str(t['cep']), str(t['logradouro']),
                str(t['numero']), str(t['complemento']), str(t['bairro']), str(t['cidade']), str(t['uf']), str(t['email'])
            ))
        except sqlite3.OperationalError:
            self.cursor.execute(query, (
                prestador_id, str(t['cnpj_cpf']), str(t['razao_social']), str(t['cep']), str(t['logradouro']),
                str(t['numero']), str(t['complemento']), str(t['bairro']), str(t['cidade']), str(t['uf']), str(t['email'])
            ))
        self.conn.commit()

    def buscar_tomadores_por_prestador(self, prestador_id):
        """Retorna a linha completa de todos os clientes cadastrados para um prestador específico."""
        self.cursor.execute("SELECT * FROM tomadores WHERE prestador_id = ? ORDER BY razao_social", (prestador_id,))
        return self.cursor.fetchall()

    def excluir_tomador(self, prestador_id, cnpj_cpf):
        """Remove o cadastro de um tomador específico associado a um determinado prestador."""
        self.cursor.execute("DELETE FROM tomadores WHERE prestador_id = ? AND cnpj_cpf = ?", (prestador_id, str(cnpj_cpf)))
        self.conn.commit()