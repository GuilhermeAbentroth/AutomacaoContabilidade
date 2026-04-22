import os
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization


class CertificadoA1:
    def __init__(self, caminho_pfx, senha):
        self.caminho_pfx = caminho_pfx
        self.senha = senha.encode('utf-8') if isinstance(senha, str) else senha
        self.chave_privada = None
        self.certificado_publico = None

    def carregar_chaves(self, log_func=None):
        """
        Abre o ficheiro .pfx usando a senha fornecida e extrai as chaves para a memória.
        """
        if not os.path.exists(self.caminho_pfx):
            raise FileNotFoundError(f"Certificado não encontrado: {self.caminho_pfx}")

        try:
            with open(self.caminho_pfx, "rb") as f:
                pfx_data = f.read()

            # Extrai as chaves usando a biblioteca cryptography
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                pfx_data,
                self.senha
            )

            self.chave_privada = private_key
            self.certificado_publico = certificate

            if log_func:
                # Vamos tentar extrair o nome da empresa de dentro do certificado para ter a certeza que abriu bem!
                assunto = certificate.subject.rfc4514_string()
                log_func(f"Cofre aberto com sucesso! Certificado carregado.", "sucesso")

            return True

        except ValueError as e:
            if log_func:
                log_func(f"ERRO: Palavra-passe do certificado incorreta ou ficheiro corrompido.", "erro")
            return False
        except Exception as e:
            if log_func:
                log_func(f"Erro inesperado ao ler certificado: {e}", "erro")
            return False

    def obter_chave_privada_pem(self):
        """Retorna a chave privada no formato PEM (necessário para assinar o XML)"""
        if not self.chave_privada:
            return None
        return self.chave_privada.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

    def obter_certificado_pem(self):
        """Retorna o certificado público no formato PEM"""
        if not self.certificado_publico:
            return None
        return self.certificado_publico.public_bytes(
            encoding=serialization.Encoding.PEM
        )