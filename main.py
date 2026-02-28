import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, simpledialog, Toplevel
import os
import sys
import json
import base64
import hmac
import hashlib
from datetime import datetime

try:
    from PIL import Image, ImageTk

    TEM_PILLOW = True
except ImportError:
    TEM_PILLOW = False
    print("AVISO: Biblioteca 'Pillow' não instalada. As imagens podem não redimensionar corretamente.")
    print("Instale usando: pip install Pillow")


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    caminho = os.path.join(base_path, relative_path)
    if os.path.exists(caminho): return caminho
    return os.path.join(base_path, "assets", relative_path)


from contabil_modulo import ContabilModulo
from fiscal_modulo import FiscalModulo
from nfse_modulo import PortalNacionalModulo
from betha_modulo import EmissorBethaModulo


class SistemaUnificadoGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Automação Abentroth v5.5")
        self.root.geometry("1100x830")
        self.root.resizable(True, True)

        if getattr(sys, 'frozen', False):
            self.pasta_exe = os.path.dirname(sys.executable)
        else:
            self.pasta_exe = os.path.dirname(os.path.abspath(__file__))

        self.caminho_config = os.path.join(self.pasta_exe, "config_sistema.json")
        self.configuracoes = self.carregar_todas_configs()

        try:
            self.root.iconbitmap(resource_path("ico.ico"))
        except:
            pass

        self.container = tk.Frame(self.root)
        self.container.pack(fill="both", expand=True)

        self.contabil = ContabilModulo(self)
        self.fiscal = FiscalModulo(self)
        self.nfse = PortalNacionalModulo(self)
        self.betha = EmissorBethaModulo(self)

        self.mostrar_menu_inicial()

    def carregar_imagem_ajustada(self, path_imagem, max_size=(300, 180)):
        if not TEM_PILLOW:
            try:
                return tk.PhotoImage(file=path_imagem)
            except:
                return tk.PhotoImage(width=max_size[0], height=max_size[1])

        if not os.path.exists(path_imagem):
            img = Image.new('RGB', max_size, color='#f0f0f0')
        else:
            try:
                img = Image.open(path_imagem)
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
            except Exception as e:
                print(f"Erro imagem: {e}")
                img = Image.new('RGB', max_size, color='#ffcccc')

        return ImageTk.PhotoImage(img)

    def carregar_todas_configs(self):
        padrao = {
            "ultimo_caminho": os.path.join(self.pasta_exe, "saida de arquivos"),
            "pasta_jpype": "",
            "pasta_playwright": "",
            "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "velocidade": "1",
            "licenca": ""  # Adicionado campo de licença
        }
        if os.path.exists(self.caminho_config):
            try:
                with open(self.caminho_config, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    padrao.update(dados)
            except:
                pass
        return padrao

    def salvar_config(self, chave=None, valor=None):
        if chave and valor is not None:
            self.configuracoes[chave] = valor
        try:
            with open(self.caminho_config, "w", encoding="utf-8") as f:
                json.dump(self.configuracoes, f, indent=4)
        except:
            pass

    # =========================================================================
    # LÓGICA DE LICENCIAMENTO
    # =========================================================================
    def licenca_valida(self):
        chave = self.configuracoes.get("licenca", "")
        if not chave:
            return False

        # Esta chave DEVE ser exatamente igual à do gerador
        from credenciais import CHAVE_SECRETA

        try:
            # 1. Decodifica a chave Base64
            texto_decodificado = base64.b64decode(chave.encode('utf-8')).decode('utf-8')
            partes = texto_decodificado.split('|')

            # Agora esperamos 3 partes: PRATICA | DATA | ASSINATURA
            if len(partes) == 3 and partes[0] == "ABENTROTH":
                data_str = partes[1]
                assinatura_recebida = partes[2]

                # 2. Recalcula a assinatura matemática localmente
                texto_base = f"ABENTROTH|{data_str}"
                assinatura_calculada = hmac.new(CHAVE_SECRETA, texto_base.encode('utf-8'), hashlib.sha256).hexdigest()[
                    :16]

                # 3. VERIFICAÇÃO ANTI-FRAUDE (Compara os lacres)
                if assinatura_recebida == assinatura_calculada:
                    # O lacre está intacto, agora verifica se a data já passou
                    data_validade = datetime.strptime(data_str, "%Y-%m-%d")
                    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

                    if hoje <= data_validade:
                        return True
                else:
                    # Se caiu aqui, o usuário alterou caracteres no Base64!
                    print("ALERTA: Tentativa de manipulação de licença detectada!")
                    return False

        except Exception:
            return False

        return False

    def verificar_acesso_modulo(self, comando_modulo):
        if self.licenca_valida():
            comando_modulo()
        else:
            self.mostrar_aviso_bloqueio()

    def mostrar_aviso_bloqueio(self):
        # Cria uma janela pop-up personalizada
        aviso = tk.Toplevel(self.root)
        aviso.title("Acesso Bloqueado")
        aviso.geometry("380x160")
        aviso.resizable(False, False)

        # Faz com que o pop-up trave a janela principal (Modal)
        aviso.transient(self.root)
        aviso.grab_set()

        # Textos do aviso
        f_msg = tk.Frame(aviso, pady=20)
        f_msg.pack()
        tk.Label(f_msg, text="❌ Licença expirada ou não cadastrada.", font=("Arial", 12, "bold"), fg="#d32f2f").pack()
        tk.Label(f_msg, text="Por favor, insira uma nova chave para continuar.", font=("Arial", 10)).pack(pady=5)

        # Botões
        f_btns = tk.Frame(aviso, pady=10)
        f_btns.pack()

        # Função que fecha o aviso e abre a tela de licença ao mesmo tempo
        def acao_alterar():
            aviso.destroy()
            self.abrir_tela_licenca()

        tk.Button(f_btns, text="Fechar", command=aviso.destroy, width=15).pack(side=tk.LEFT, padx=10)
        tk.Button(f_btns, text="Alterar Chave", command=acao_alterar, bg="#242424", fg="white",
                  font=("Arial", 9, "bold"), width=15).pack(side=tk.LEFT, padx=10)

    def abrir_tela_licenca(self):
        janela = tk.Toplevel(self.root)
        janela.title("Gerenciador de Licença")
        janela.geometry("400x250")
        janela.resizable(False, False)

        f_status = tk.Frame(janela, pady=20)
        f_status.pack()

        if self.licenca_valida():
            try:
                chave = self.configuracoes.get("licenca", "")
                texto = base64.b64decode(chave.encode('utf-8')).decode('utf-8')
                data_str = texto.split('|')[1]
                data_br = datetime.strptime(data_str, "%Y-%m-%d").strftime("%d/%m/%Y")
                tk.Label(f_status, text="✅ Status: ATIVA", font=("Arial", 12, "bold"), fg="green").pack()
                tk.Label(f_status, text=f"Válida até: {data_br}", font=("Arial", 10)).pack()
            except:
                pass
        else:
            tk.Label(f_status, text="❌ Status: EXPIRADA / INVÁLIDA", font=("Arial", 12, "bold"), fg="red").pack()

        f_input = tk.Frame(janela, pady=10)
        f_input.pack()
        tk.Label(f_input, text="Insira a nova chave de ativação:", font=("Arial", 9)).pack()

        var_chave = tk.StringVar()
        ent_chave = tk.Entry(f_input, textvariable=var_chave, width=40, font=("Arial", 10), justify="center")
        ent_chave.pack(pady=5)

        def salvar_nova_licenca():
            nova = var_chave.get().strip()
            if nova:
                self.salvar_config("licenca", nova)
                if self.licenca_valida():
                    messagebox.showinfo("Sucesso", "Licença ativada com sucesso!")
                    janela.destroy()
                else:
                    messagebox.showerror("Erro", "A chave inserida é inválida ou já expirou.")
            else:
                messagebox.showwarning("Atenção", "Insira uma chave válida.")

        tk.Button(f_input, text="Ativar Licença", command=salvar_nova_licenca, bg="#228B22", fg="white",
                  font=("Arial", 10, "bold"), width=20).pack(pady=10)

    # =========================================================================

    def mostrar_info_sistema(self):
        info_texto = (
            "Autor: Guilherme Abentroth\n"
            "Versão: 5.5\n"
            "Data da Versão: 28/02/2026\n\n"
            "Notas da Versão:\n"
            "1. Adicionado bloqueio por licenciamento.\n"
            "2. Modulo emissor NFSE e C6 Bank implementados.\n")
        messagebox.showinfo("Sobre o Sistema", info_texto)

    def abrir_tela_config(self):
        senha = simpledialog.askstring("Restrito", "Digite a senha de admin:", show='*')
        if senha != "579499":
            messagebox.showerror("Erro", "Senha incorreta!")
            return

        janela = tk.Toplevel(self.root)
        janela.title("Configurações")
        janela.geometry("650x550")

        def criar_linha(txt, chave):
            f = tk.Frame(janela, padx=20, pady=5)
            f.pack(fill="x")
            tk.Label(f, text=txt, font=("Arial", 9, "bold")).pack(anchor="w")
            sf = tk.Frame(f)
            sf.pack(fill="x")
            var = tk.StringVar(value=self.configuracoes.get(chave, ""))
            tk.Entry(sf, textvariable=var).pack(side=tk.LEFT, fill="x", expand=True)

            def b():
                p = filedialog.askopenfilename() if "chrome" in chave else filedialog.askdirectory()
                if p: var.set(p)

            def ok(): self.salvar_config(chave, var.get()); messagebox.showinfo("OK", "Salvo!")

            tk.Button(sf, text="...", command=b).pack(side=tk.LEFT)
            tk.Button(sf, text="OK", command=ok).pack(side=tk.LEFT)

        def criar_vel():
            f = tk.Frame(janela, padx=20, pady=10)
            f.pack(fill="x")
            tk.Label(f, text="Velocidade (1=Normal, 2=Rápido, 3=Turbo):", font=("Arial", 9, "bold")).pack(anchor="w")
            var = tk.StringVar(value=self.configuracoes.get("velocidade", "1"))
            tk.OptionMenu(f, var, "1", "2", "3").pack(side=tk.LEFT)
            tk.Button(f, text="OK", command=lambda: [self.salvar_config("velocidade", var.get()),
                                                     messagebox.showinfo("OK", "Salvo")]).pack(side=tk.LEFT)

        criar_linha("Pasta JPype:", "pasta_jpype")
        criar_linha("Pasta Playwright:", "pasta_playwright")
        criar_linha("Executável Chrome:", "chrome_path")
        criar_vel()

    def log_msg(self, mensagem, tipo="info", divisor=False):
        if hasattr(self, 'txt_log') and self.txt_log.winfo_exists():
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.txt_log.config(state='normal')
            if divisor: self.txt_log.insert(tk.END, "\n" + "=" * 90 + "\n")
            tag = tipo if tipo in ["erro", "sucesso"] else "info"
            self.txt_log.tag_config("erro", foreground="red")
            self.txt_log.tag_config("sucesso", foreground="green")
            self.txt_log.insert(tk.END, f"[{timestamp}] {mensagem}\n", tag)
            self.txt_log.see(tk.END)
            self.txt_log.config(state='disabled')
            self.root.update()

    def limpar_tela(self):
        for widget in self.container.winfo_children(): widget.destroy()

    def carregar_logo(self, parent):
        path_logo = resource_path("logo.png")
        if os.path.exists(path_logo):
            try:
                img = tk.PhotoImage(file=path_logo)
                self.img_logo = img.subsample(3, 3)
                tk.Label(parent, image=self.img_logo).pack()
            except:
                tk.Label(parent, text="SISTEMA AUTOMAÇÃO").pack()
        else:
            tk.Label(parent, text="SISTEMA AUTOMAÇÃO").pack()

    def mostrar_menu_inicial(self):
        self.limpar_tela()

        # Botões de Topo (Config, Info e LICENÇA)
        tk.Button(self.container, text="🔑 Licença", command=self.abrir_tela_licenca, bg="#eee", relief=tk.FLAT,
                  font=("Arial", 10, "bold")).place(x=870, y=10)
        tk.Button(self.container, text="ℹ️", command=self.mostrar_info_sistema, bg="#eee", relief=tk.FLAT,
                  font=("Arial", 12)).place(x=960, y=10)
        tk.Button(self.container, text="⚙", command=self.abrir_tela_config, bg="#eee", relief=tk.FLAT,
                  font=("Arial", 12)).place(x=1000, y=10)

        f_l = tk.Frame(self.container, pady=20)
        f_l.pack()
        self.carregar_logo(f_l)
        f_b = tk.Frame(self.container, pady=80)
        f_b.pack()

        # Botões envolvidos no verificador de licença
        tk.Button(f_b, text="FISCAL", command=lambda: self.verificar_acesso_modulo(self.tela_fiscal),
                  bg="#228B22", fg="white", font=("Arial", 16, "bold"), width=15, height=4).pack(side=tk.LEFT, padx=15)

        tk.Button(f_b, text="CONTABIL", command=lambda: self.verificar_acesso_modulo(self.tela_contabil),
                  bg="#005A9C", fg="white", font=("Arial", 16, "bold"), width=15, height=4).pack(side=tk.LEFT, padx=15)

        tk.Button(f_b, text="PORTAL NACIONAL", command=lambda: self.verificar_acesso_modulo(self.nfse.tela_nfse),
                  bg="#f39200", fg="white", font=("Arial", 16, "bold"), width=15, height=4).pack(side=tk.LEFT, padx=15)

        tk.Button(f_b, text="EMISSOR NFSE", command=lambda: self.verificar_acesso_modulo(self.betha.tela_emissor_betha),
                  bg="#8e44ad", fg="white", font=("Arial", 16, "bold"), width=15, height=4).pack(side=tk.LEFT, padx=15)

        tk.Label(self.container, text="Powered by: Guilherme Abentroth", font=("Arial Black", 10)).pack(side=tk.BOTTOM,
                                                                                                        anchor="w",
                                                                                                        padx=20,
                                                                                                        pady=20)

    # -------------------------------------------------------------------------
    # RESTANTE DO CÓDIGO INTACTO
    # -------------------------------------------------------------------------
    def construir_tela_unico_modelo(self, nome_banco, nome_imagem, cor_titulo, funcao_backend):
        self.limpar_tela()

        f_top = tk.Frame(self.container, pady=10)
        f_top.pack()
        tk.Label(f_top, text=f"Importação {nome_banco}", font=("Arial", 18, "bold"), fg=cor_titulo).pack()
        tk.Label(f_top, text="Clique na imagem abaixo para selecionar o arquivo e iniciar.", font=("Arial", 10)).pack()

        def bridge(lista):
            self.contabil.gerar_ofx(self.log_msg, lista)

        f_img = tk.Frame(self.container, pady=20)
        f_img.pack()

        path_img = resource_path(nome_imagem)
        self.img_temp = self.carregar_imagem_ajustada(path_img, max_size=(350, 250))

        btn_img = tk.Button(
            f_img,
            image=self.img_temp,
            command=lambda: funcao_backend(self.log_msg, bridge),
            bd=4,
            relief=tk.RAISED
        )
        btn_img.pack()

        tk.Label(f_img, text=f"Modelo Padrão {nome_banco}", font=("Arial", 9, "bold"), pady=5, fg="#333").pack()

        f_log = tk.Frame(self.container, padx=20, pady=5)
        f_log.pack(fill="both", expand=True)
        tk.Label(f_log, text="Log de Processamento:", font=("Arial", 10, "bold")).pack(anchor="w")
        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=10, state='disabled')
        self.txt_log.pack(pady=5)

        f_btns = tk.Frame(self.container, pady=10)
        f_btns.pack()
        tk.Button(f_btns, text="Voltar", command=self.tela_contabil,
                  bg="#666", fg="white", width=15, height=2).pack()

    def tela_escolha_stone(self):
        self.construir_tela_unico_modelo("Stone", "STONE.png", "#00A868", self.contabil.fluxo_stone)

    def tela_escolha_pagbank(self):
        self.construir_tela_unico_modelo("PagBank", "PAGBANK.png", "#8BC34A", self.contabil.fluxo_pagbank)

    def tela_escolha_sicredi(self):
        self.construir_tela_unico_modelo("Sicredi", "SICREDI.png", "#32BC43", self.contabil.fluxo_sicredi)

    def tela_escolha_ailos(self):
        self.construir_tela_unico_modelo("Ailos", "AILOS.png", "#005A9C", self.contabil.fluxo_ailos)

    def tela_escolha_ifood(self):
        self.construir_tela_unico_modelo("iFood", "IFOOD.png", "#EA1D2C", self.contabil.fluxo_ifood)

    def tela_escolha_cresol(self):
        self.construir_tela_unico_modelo("Cresol em construção  ", "CRESOL.png", "#006B3F", self.contabil.fluxo_cresol)

    def tela_escolha_c6(self):
        self.construir_tela_unico_modelo("C6 Bank", "C6.png", "#242424", self.contabil.fluxo_c6)

    def tela_escolha_caixa(self):
        self.limpar_tela()

        f_top = tk.Frame(self.container, pady=5)
        f_top.pack()
        tk.Label(f_top, text="Selecione o Modelo do Extrato CAIXA", font=("Arial", 16, "bold"), fg="#005CA9").pack()
        tk.Label(f_top, text="Clique na imagem para iniciar o processamento", font=("Arial", 10)).pack()

        f_imgs = tk.Frame(self.container, pady=5)
        f_imgs.pack()

        def bridge(lista): self.contabil.gerar_ofx(self.log_msg, lista)

        max_dim = (220, 130)

        f_linha1 = tk.Frame(f_imgs)
        f_linha1.pack(pady=5)

        f_linha2 = tk.Frame(f_imgs)
        f_linha2.pack(pady=5)

        f_op1 = tk.Frame(f_linha1)
        f_op1.pack(side=tk.LEFT, padx=15, anchor="n")
        self.img_caixa1 = self.carregar_imagem_ajustada(resource_path("CAIXA.png"), max_dim)
        tk.Button(f_op1, image=self.img_caixa1, command=lambda: self.contabil.fluxo_caixa_v1(self.log_msg, bridge),
                  bd=4, relief=tk.RAISED).pack()
        tk.Label(f_op1, text="Caixa V1 (Antigo)", font=("Arial", 9, "bold"), pady=2).pack()

        f_op2 = tk.Frame(f_linha1)
        f_op2.pack(side=tk.LEFT, padx=15, anchor="n")
        self.img_caixa2_h = self.carregar_imagem_ajustada(resource_path("CAIXA2.png"), max_dim)
        tk.Button(f_op2, image=self.img_caixa2_h,
                  command=lambda: self.contabil.fluxo_caixa_v2_horizontal(self.log_msg, bridge), bd=4,
                  relief=tk.RAISED).pack()
        tk.Label(f_op2, text="Caixa V2 (Horizontal)", font=("Arial", 9, "bold"), pady=2).pack()

        f_op3 = tk.Frame(f_linha2)
        f_op3.pack(side=tk.LEFT, padx=15, anchor="n")
        self.img_caixa2_v = self.carregar_imagem_ajustada(resource_path("CAIXA2.png"), max_dim)
        tk.Button(f_op3, image=self.img_caixa2_v,
                  command=lambda: self.contabil.fluxo_caixa_v2_vertical(self.log_msg, bridge), bd=4,
                  relief=tk.RAISED).pack()
        tk.Label(f_op3, text="Caixa V2 (Vertical) em manutenção", font=("Arial", 9, "bold"), pady=2).pack()

        f_op4 = tk.Frame(f_linha2)
        f_op4.pack(side=tk.LEFT, padx=15, anchor="n")
        self.img_caixa3 = self.carregar_imagem_ajustada(resource_path("CAIXA3.png"), max_dim)
        tk.Button(f_op4, image=self.img_caixa3, command=lambda: self.contabil.fluxo_caixa_v3(self.log_msg, bridge),
                  bd=4, relief=tk.RAISED).pack()
        tk.Label(f_op4, text="Caixa V3 (D/C)", font=("Arial", 9, "bold"), pady=2).pack()

        f_log = tk.Frame(self.container, padx=20, pady=5)
        f_log.pack(fill="both", expand=True)
        tk.Label(f_log, text="Log de Processamento:").pack(anchor="w")
        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=8, state='disabled')
        self.txt_log.pack(pady=5)

        tk.Button(self.container, text="Voltar", command=self.tela_contabil, bg="#666", fg="white", width=15,
                  height=2).pack(pady=5)

    def tela_escolha_santander(self):
        self.limpar_tela()

        f_top = tk.Frame(self.container, pady=10)
        f_top.pack()
        tk.Label(f_top, text="Selecione o Modelo do Extrato Santander", font=("Arial", 16, "bold"), fg="#ec0000").pack()
        tk.Label(f_top, text="Clique na imagem para iniciar o processamento", font=("Arial", 10)).pack()

        f_imgs = tk.Frame(self.container, pady=15)
        f_imgs.pack()

        def bridge(lista): self.contabil.gerar_ofx(self.log_msg, lista)

        max_dim = (300, 180)

        f_op1 = tk.Frame(f_imgs)
        f_op1.pack(side=tk.LEFT, padx=30, anchor="n")

        path_img1 = resource_path("SANTANDER.png")
        self.img_santander1 = self.carregar_imagem_ajustada(path_img1, max_dim)

        tk.Button(f_op1, image=self.img_santander1,
                  command=lambda: self.contabil.fluxo_santander_v1(self.log_msg, bridge), bd=4,
                  relief=tk.RAISED).pack()
        tk.Label(f_op1, text="Santander (Padrão)", font=("Arial", 9, "bold"), pady=5).pack()

        f_op2 = tk.Frame(f_imgs)
        f_op2.pack(side=tk.LEFT, padx=30, anchor="n")

        path_img2 = resource_path("SANTANDER2.png")
        self.img_santander2 = self.carregar_imagem_ajustada(path_img2, max_dim)

        tk.Button(f_op2, image=self.img_santander2,
                  command=lambda: self.contabil.fluxo_santander_v2(self.log_msg, bridge), bd=4,
                  relief=tk.RAISED).pack()
        tk.Label(f_op2, text="Santander (Empresas)", font=("Arial", 9, "bold"), pady=5).pack()

        f_log = tk.Frame(self.container, padx=20, pady=10)
        f_log.pack(fill="both", expand=True)
        tk.Label(f_log, text="Log de Processamento:").pack(anchor="w")
        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=12, state='disabled')
        self.txt_log.pack(pady=5)

        tk.Button(self.container, text="Voltar", command=self.tela_contabil, bg="#666", fg="white", width=15,
                  height=2).pack(pady=10)

    def tela_escolha_bb(self):
        self.limpar_tela()

        f_top = tk.Frame(self.container, pady=10)
        f_top.pack()
        tk.Label(f_top, text="Selecione o Modelo do Extrato BB", font=("Arial", 16, "bold"), fg="#fdb913").pack()
        tk.Label(f_top, text="Clique na imagem para iniciar o processamento", font=("Arial", 10)).pack()

        f_imgs = tk.Frame(self.container, pady=15)
        f_imgs.pack()

        def bridge(lista): self.contabil.gerar_ofx(self.log_msg, lista)

        max_dim = (300, 180)

        f_op1 = tk.Frame(f_imgs)
        f_op1.pack(side=tk.LEFT, padx=30, anchor="n")

        path_img1 = resource_path("modelo_bb1.png")
        self.img_bb1 = self.carregar_imagem_ajustada(path_img1, max_dim)

        tk.Button(f_op1, image=self.img_bb1, command=lambda: self.contabil.fluxo_bb_v1(self.log_msg, bridge), bd=4,
                  relief=tk.RAISED).pack()
        tk.Label(f_op1, text="BB Modelo 1 (Padrão)", font=("Arial", 9, "bold"), pady=5).pack()

        f_op2 = tk.Frame(f_imgs)
        f_op2.pack(side=tk.LEFT, padx=30, anchor="n")

        path_img2 = resource_path("modelo_bb2.png")
        self.img_bb2 = self.carregar_imagem_ajustada(path_img2, max_dim)

        tk.Button(f_op2, image=self.img_bb2, command=lambda: self.contabil.fluxo_bb_v2(self.log_msg, bridge), bd=4,
                  relief=tk.RAISED).pack()
        tk.Label(f_op2, text="BB Modelo 2 (Digital)", font=("Arial", 9, "bold"), pady=5).pack()

        f_log = tk.Frame(self.container, padx=20, pady=10)
        f_log.pack(fill="both", expand=True)
        tk.Label(f_log, text="Log de Processamento:").pack(anchor="w")
        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=12, state='disabled')
        self.txt_log.pack(pady=5)

        tk.Button(self.container, text="Voltar", command=self.tela_contabil, bg="#666", fg="white", width=15,
                  height=2).pack(pady=10)

    def tela_escolha_sicoob(self):
        self.limpar_tela()

        f_top = tk.Frame(self.container, pady=10)
        f_top.pack()
        tk.Label(f_top, text="Selecione o Modelo do Extrato Sicoob", font=("Arial", 16, "bold"), fg="#00ae9d").pack()
        tk.Label(f_top, text="Clique na imagem para iniciar o processamento", font=("Arial", 10)).pack()

        f_imgs = tk.Frame(self.container, pady=15)
        f_imgs.pack()

        def bridge(lista): self.contabil.gerar_ofx(self.log_msg, lista)

        max_dim = (300, 180)

        f_op1 = tk.Frame(f_imgs)
        f_op1.pack(side=tk.LEFT, padx=30, anchor="n")

        path_img1 = resource_path("sicoob_celular.png")
        self.img_sicoob1 = self.carregar_imagem_ajustada(path_img1, max_dim)

        tk.Button(f_op1, image=self.img_sicoob1,
                  command=lambda: self.contabil.fluxo_sicoob_celular(self.log_msg, bridge), bd=4,
                  relief=tk.RAISED).pack()
        tk.Label(f_op1, text="Sicoob Celular (App)", font=("Arial", 9, "bold"), pady=5).pack()

        f_op2 = tk.Frame(f_imgs)
        f_op2.pack(side=tk.LEFT, padx=30, anchor="n")

        path_img2 = resource_path("sicoob_pdf.png")
        self.img_sicoob2 = self.carregar_imagem_ajustada(path_img2, max_dim)

        tk.Button(f_op2, image=self.img_sicoob2, command=lambda: self.contabil.fluxo_sicoob_pdf(self.log_msg, bridge),
                  bd=4,
                  relief=tk.RAISED).pack()
        tk.Label(f_op2, text="Sicoob PDF (Desktop)", font=("Arial", 9, "bold"), pady=5).pack()

        f_log = tk.Frame(self.container, padx=20, pady=10)
        f_log.pack(fill="both", expand=True)
        tk.Label(f_log, text="Log de Processamento:").pack(anchor="w")
        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=12, state='disabled')
        self.txt_log.pack(pady=5)

        tk.Button(self.container, text="Voltar", command=self.tela_contabil, bg="#666", fg="white", width=15,
                  height=2).pack(pady=10)

    def tela_contabil(self):
        self.limpar_tela()
        f_l = tk.Frame(self.container, pady=10)
        f_l.pack()
        self.carregar_logo(f_l)

        tk.Label(self.container, text="Log de Processamento:").pack(anchor="w", padx=20)
        self.txt_log = scrolledtext.ScrolledText(self.container, width=125, height=15, state='disabled')
        self.txt_log.pack(padx=20, pady=5)

        f_b = tk.Frame(self.container, pady=20)
        f_b.pack()

        def bridge(lista): self.contabil.gerar_ofx(self.log_msg, lista)

        f_b1 = tk.Frame(f_b)
        f_b1.pack(pady=5)

        tk.Button(f_b1, text="Banco do Brasil", command=self.tela_escolha_bb, bg="#fdb913", fg="white",
                  font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b1, text="Caixa", command=self.tela_escolha_caixa,
                  bg="#005CA9", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b1, text="Santander", command=self.tela_escolha_santander,
                  bg="#ec0000", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b1, text="Sicredi", command=self.tela_escolha_sicredi,
                  bg="#32BC43", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        f_b2 = tk.Frame(f_b)
        f_b2.pack(pady=5)

        tk.Button(f_b2, text="Sicoob", command=self.tela_escolha_sicoob, bg="#00ae9d", fg="white",
                  font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b2, text="Ailos", command=self.tela_escolha_ailos,
                  bg="#005A9C", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b2, text="Stone", command=self.tela_escolha_stone,
                  bg="#00A868", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b2, text="PagBank", command=self.tela_escolha_pagbank,
                  bg="#8BC34A", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        f_b3 = tk.Frame(f_b)
        f_b3.pack(pady=5)

        tk.Button(f_b3, text="iFood", command=self.tela_escolha_ifood,
                  bg="#EA1D2C", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b3, text="Cresol", command=self.tela_escolha_cresol,
                  bg="#006B3F", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b3, text="C6 Bank", command=self.tela_escolha_c6,
                  bg="#242424", fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b3, text="Excel > OFX", command=lambda: self.contabil.gerar_ofx(self.log_msg), bg="#7f8c8d",
                  fg="white", font=("Arial", 9, "bold"), width=15, height=2).pack(side=tk.LEFT, padx=5)

        tk.Button(f_b3, text="Voltar", command=self.mostrar_menu_inicial, bg="#666", fg="white", width=15,
                  height=2).pack(side=tk.LEFT, padx=5)

    def tela_fiscal(self):
        self.limpar_tela()
        f_l = tk.Frame(self.container, pady=10)
        f_l.pack()
        self.carregar_logo(f_l)

        f_c = tk.Frame(self.container, padx=20, pady=10)
        f_c.pack(fill="x")
        self.entry_saida = tk.Entry(f_c, font=("Arial", 10), width=90)
        self.entry_saida.pack(side=tk.LEFT, padx=10)
        self.entry_saida.insert(0, self.configuracoes.get("ultimo_caminho"))
        tk.Button(f_c, text="Selecionar", command=self.selecionar_p_f).pack(side=tk.LEFT)

        self.txt_log = scrolledtext.ScrolledText(self.container, width=125, height=15, state='disabled')
        self.txt_log.pack(padx=20, pady=5)

        f_btns = tk.Frame(self.container, pady=15)
        f_btns.pack()
        tk.Button(f_btns, text="PROCESSAR", command=self.exec_f_logic, bg="#228B22", fg="white", width=25,
                  height=2).pack(side=tk.LEFT, padx=10)
        tk.Button(f_btns, text="Voltar", command=self.mostrar_menu_inicial, bg="#666", fg="white", width=15,
                  height=2).pack(side=tk.LEFT)

    def selecionar_p_f(self):
        p = filedialog.askdirectory()
        if p: self.entry_saida.delete(0, tk.END); self.entry_saida.insert(0, p)

    def exec_f_logic(self):
        path_atual = self.entry_saida.get().strip()
        if not path_atual: messagebox.showwarning("Atenção", "Selecione uma pasta de saída primeiro."); return

        resp = messagebox.askyesno("Confirmar", f"Salvar arquivos em:\n{path_atual}\n\nConfirma?")
        if not resp:
            novo = filedialog.askdirectory()
            if novo:
                self.entry_saida.delete(0, tk.END)
                self.entry_saida.insert(0, novo)
                path_atual = novo
            else:
                return

        self.salvar_config("ultimo_caminho", path_atual)
        self.fiscal.executar_fiscal(path_atual, self.log_msg)
        messagebox.showinfo("Sucesso", "Concluído.")


if __name__ == "__main__":
    root = tk.Tk()
    app = SistemaUnificadoGUI(root)
    root.mainloop()