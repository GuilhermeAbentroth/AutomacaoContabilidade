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
                            CREATE TABLE IF NOT EXISTS prestadores
                            (
                                id
                                INTEGER
                                PRIMARY
                                KEY
                                AUTOINCREMENT,
                                cnpj
                                TEXT
                                UNIQUE,
                                im
                                TEXT,
                                nome
                                TEXT,
                                caminho_pfx
                                TEXT,
                                senha_pfx
                                TEXT,
                                cnae
                                TEXT,
                                cod_servico
                                TEXT,
                                item_lista
                                TEXT,
                                exigibilidade_iss
                                TEXT,
                                natureza_operacao
                                TEXT,
                                iss_retido
                                TEXT,
                                aliquota_iss
                                TEXT

                            )
                            """)
        # Tabela de Tomadores (Clientes / Destinatários)
        self.cursor.execute("""
                            CREATE TABLE IF NOT EXISTS tomadores
                            (
                                id
                                INTEGER
                                PRIMARY
                                KEY
                                AUTOINCREMENT,
                                prestador_id
                                INTEGER,
                                cnpj_cpf
                                TEXT,
                                razao_social
                                TEXT,
                                cep
                                TEXT,
                                logradouro
                                TEXT,
                                numero
                                TEXT,
                                complemento
                                TEXT,
                                bairro
                                TEXT,
                                cidade
                                TEXT,
                                uf
                                TEXT,
                                email
                                TEXT,
                                UNIQUE
                            (
                                prestador_id,
                                cnpj_cpf
                            ),
                                FOREIGN KEY
                            (
                                prestador_id
                            ) REFERENCES prestadores
                            (
                                id
                            )
                                )
                            """)
        self.conn.commit()
        try:
            self.cursor.execute("ALTER TABLE prestadores ADD COLUMN nbs TEXT DEFAULT ''")
            self.conn.commit()
        except Exception:
            pass

        # Migração automática — adiciona colunas se não existirem
        for coluna, tipo in [
            ("loc_prestacao_ibge", "TEXT"),
            ("loc_prestacao_nome", "TEXT"),
            ("loc_prestacao_uf", "TEXT"),
            ("ultimo_cod_servico", "TEXT"),
            ("ultimo_iss_aliquota", "TEXT"),  # Salva alíquota do ISS por cliente
            ("ultimo_iss_retido", "TEXT")  # Salva retenção do ISS por cliente
        ]:
            try:
                self.cursor.execute(f"ALTER TABLE tomadores ADD COLUMN {coluna} {tipo}")
                self.conn.commit()
            except Exception:
                pass

        # Migração — município de emissão (cLocEmi) e ambiente por prestador,
        # necessários para o Emissor Portal Nacional (deixa de ser um único
        # município fixo no código, já que agora atendemos várias cidades).
        # IMPORTANTE: o default começa em "Produção Restrita (Homologação)"
        # de propósito — nunca queremos que um prestador sem cidade/ambiente
        # configurado caia em Produção por acidente numa API síncrona que
        # gera NFS-e de verdade.
        for coluna, tipo in [
            ("municipio_emissao_ibge", "TEXT"),
            ("municipio_emissao_nome", "TEXT"),
            ("municipio_emissao_uf", "TEXT"),
            ("ambiente_emissao", "TEXT DEFAULT 'Produção Restrita (Homologação)'"),
        ]:
            try:
                self.cursor.execute(f"ALTER TABLE prestadores ADD COLUMN {coluna} {tipo}")
                self.conn.commit()
            except Exception:
                pass

        # Normaliza registros que já tinham sido migrados com o default
        # antigo ("Produção") antes desta correção — ninguém usou o Emissor
        # Portal Nacional ainda, então é seguro forçar de volta pra Restrita.
        try:
            self.cursor.execute("""
                                UPDATE prestadores
                                SET ambiente_emissao = 'Produção Restrita (Homologação)'
                                WHERE ambiente_emissao IS NULL
                                   OR ambiente_emissao IN ('', 'Produção')
                                """)
            self.conn.commit()
        except Exception:
            pass

        # Histórico de emissões via Portal Nacional (API síncrona — não precisa
        # da máquina de estados de polling que o monitor_notas.py usa pra Betha).
        self.cursor.execute("""
                            CREATE TABLE IF NOT EXISTS notas_emitidas_pn
                            (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                dt_emissao TEXT,
                                prestador_cnpj TEXT,
                                prestador_nome TEXT,
                                tomador_nome TEXT,
                                ambiente TEXT,
                                status TEXT,
                                numero_nfse TEXT,
                                chave_acesso TEXT,
                                caminho_pdf TEXT,
                                caminho_xml TEXT,
                                mensagem_erro TEXT
                            )
                            """)
        self.conn.commit()

    # --- OPERAÇÕES DO PRESTADOR ---
    def salvar_prestador(self, d):
        """Insere ou atualiza os dados fiscais do prestador sem alterar o ID (preservando tomadores)."""
        self.cursor.execute("SELECT id FROM prestadores WHERE cnpj = ?", (str(d['cnpj']),))
        existing = self.cursor.fetchone()

        if existing:
            # UPDATE preserva o id e mantém os tomadores vinculados
            self.cursor.execute("""
                                UPDATE prestadores
                                SET im=?,
                                    nome=?,
                                    caminho_pfx=?,
                                    senha_pfx=?,
                                    cnae=?,
                                    cod_servico=?,
                                    item_lista=?,
                                    exigibilidade_iss=?,
                                    natureza_operacao=?,
                                    iss_retido=?,
                                    aliquota_iss=?,
                                    nbs=?
                                WHERE cnpj = ?
                                """, (str(d['im']), str(d['nome']), str(d['pfx']), str(d['senha']),
                                      str(d['cnae']), str(d['item']), str(d['item']), str(d['exigibilidade']),
                                      str(d['natureza']), str(d['iss_retido']), str(d['aliquota']),
                                      str(d.get('nbs', '')), str(d['cnpj'])))
            prestador_id = existing[0]
        else:
            # INSERT caso não exista
            self.cursor.execute("""
                                INSERT INTO prestadores
                                (cnpj, im, nome, caminho_pfx, senha_pfx, cnae, cod_servico, item_lista,
                                 exigibilidade_iss, natureza_operacao, iss_retido, aliquota_iss, nbs)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (str(d['cnpj']), str(d['im']), str(d['nome']), str(d['pfx']), str(d['senha']),
                                      str(d['cnae']), str(d['item']), str(d['item']), str(d['exigibilidade']),
                                      str(d['natureza']), str(d['iss_retido']), str(d['aliquota']),
                                      str(d.get('nbs', ''))))
            prestador_id = self.cursor.lastrowid

        self.conn.commit()
        return prestador_id

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
                            UPDATE prestadores
                            SET caminho_pfx = ?,
                                senha_pfx   = ?
                            WHERE cnpj = ?
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
        """Insere ou atualiza o cadastro do cliente (tomador) com dados de prestação, serviço e tributação de ISS."""
        query = """
            INSERT OR REPLACE INTO tomadores 
            (prestador_id, cnpj_cpf, razao_social, cep, logradouro, numero, complemento, 
            bairro, cidade, uf, email, loc_prestacao_ibge, loc_prestacao_nome, 
            loc_prestacao_uf, ultimo_cod_servico, ultimo_iss_aliquota, ultimo_iss_retido)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self.cursor.execute(query, (
                prestador_id, str(t['cnpj_cpf']), str(t['razao_social']), str(t['cep']),
                str(t['logradouro']), str(t['numero']), str(t['complemento']), str(t['bairro']),
                str(t['cidade']), str(t['uf']), str(t['email']),
                str(t.get('loc_prestacao_ibge', '')), str(t.get('loc_prestacao_nome', '')),
                str(t.get('loc_prestacao_uf', '')), str(t.get('ultimo_cod_servico', '')),
                str(t.get('ultimo_iss_aliquota', '')), str(t.get('ultimo_iss_retido', ''))
            ))
        except Exception as e:
            print(f"Erro salvar_tomador: {e}")
        self.conn.commit()

    def buscar_tomadores_por_prestador(self, prestador_id):
        """Retorna a linha completa de todos os clientes cadastrados para um prestador específico."""
        self.cursor.execute("SELECT * FROM tomadores WHERE prestador_id = ? ORDER BY razao_social", (prestador_id,))
        return self.cursor.fetchall()

    def excluir_tomador(self, prestador_id, cnpj_cpf):
        """Remove o cadastro de um tomador específico associado a um determinado prestador."""
        self.cursor.execute("DELETE FROM tomadores WHERE prestador_id = ? AND cnpj_cpf = ?",
                            (prestador_id, str(cnpj_cpf)))
        self.conn.commit()

    # --- MUNICÍPIO/AMBIENTE DE EMISSÃO (Portal Nacional) ---
    def atualizar_municipio_emissao(self, cnpj, ibge, nome_cidade, uf, ambiente):
        """Grava a cidade do emitente (cLocEmi) e o ambiente (Produção/Produção Restrita) por prestador."""
        self.cursor.execute("""
                            UPDATE prestadores
                            SET municipio_emissao_ibge = ?,
                                municipio_emissao_nome = ?,
                                municipio_emissao_uf   = ?,
                                ambiente_emissao       = ?
                            WHERE cnpj = ?
                            """, (str(ibge), str(nome_cidade), str(uf), str(ambiente), str(cnpj)))
        self.conn.commit()

    # --- HISTÓRICO DE EMISSÕES — PORTAL NACIONAL ---
    def registrar_emissao_pn(self, d):
        """Grava o resultado (sucesso ou erro) de uma tentativa de emissão via Portal Nacional."""
        self.cursor.execute("""
                            INSERT INTO notas_emitidas_pn
                            (dt_emissao, prestador_cnpj, prestador_nome, tomador_nome, ambiente,
                             status, numero_nfse, chave_acesso, caminho_pdf, caminho_xml, mensagem_erro)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                str(d.get('dt_emissao', '')), str(d.get('prestador_cnpj', '')),
                                str(d.get('prestador_nome', '')), str(d.get('tomador_nome', '')),
                                str(d.get('ambiente', '')), str(d.get('status', '')),
                                str(d.get('numero_nfse', '')), str(d.get('chave_acesso', '')),
                                str(d.get('caminho_pdf', '')), str(d.get('caminho_xml', '')),
                                str(d.get('mensagem_erro', '')),
                            ))
        self.conn.commit()
        return self.cursor.lastrowid

    def listar_emissoes_pn(self, limite=200):
        """Retorna o histórico de emissões via Portal Nacional, mais recentes primeiro."""
        self.cursor.execute("SELECT * FROM notas_emitidas_pn ORDER BY id DESC LIMIT ?", (limite,))
        return self.cursor.fetchall()

    def buscar_tomador_por_cnpj_global(self, cnpj_cpf: str):
        """Busca dados cadastrais de um tomador em qualquer prestador pelo CNPJ/CPF."""
        self.cursor.execute("""
                            SELECT razao_social,
                                   cep,
                                   logradouro,
                                   numero,
                                   complemento,
                                   bairro,
                                   cidade,
                                   uf,
                                   email
                            FROM tomadores
                            WHERE cnpj_cpf = ?
                            ORDER BY id DESC LIMIT 1
                            """, (str(cnpj_cpf),))
        return self.cursor.fetchone()