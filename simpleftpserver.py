import threading
import socket
import selectors
import queue
import os
import sys
import time
import stat
import pwd
import grp
import shutil
from functools import wraps

#------------------------------------------------#
## Initialisation des parametres de ftp ##
#------------------------------------------------#

HOST = socket.gethostbyname(socket.gethostname())
PORT = 21
CLIENT_size = 5


def str_color(string, color) -> str:
    return "\033["+str(color)+"m" + str(string) + "\033[0m "


def log(obj=None, description=None):
    timemsg = time.strftime("%Y-%m-%d %H-%M-%S ")
    print((str_color(timemsg, 31)+(str_color(obj, 33)if obj != None else "") +
           (str_color(description, 32)if description != None else "")))


#-------------------------#
## Ftp threading serveur ##
#-------------------------#

class FTPServer:
    def __init__(self, host="127.0.0.1", port=21, client_size=5, allow_delete=True):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.addr = (host, port)
        self.client_size = client_size
        self.allow_delete = allow_delete

        self.__stop_request = threading.Event()
        self.__is_stop = False
        self.clients = {}
        self.selector = selectors.DefaultSelector()

        self.codes_rep = self.Codes_rep()
        self.cmds_list = self.Cmds_list()

        self.initial()

        
    
    def initial(self):
        self.authenticated = False
        self.username = None
        self.passwd = None

        self.mode_is_Ascii = False

        self.pathname = os.getenv("HOME")

        self.pasv_mode = True
        self.serverSock = None

        self.pos = 0
        self.rest = False
        self.dataSock, self.dataAddress = None, None

        self.oldname = None

    #----------------------#
    ## Ftp serveur outils ##
    #----------------------#

    def ftp_config(func):
        @wraps(func)
        def _deco(self, *args):
            if not len(args) > 1:
                log(func.__name__, *args)
            else:
                log(func.__name__, *args[1:])
            if self.authenticated:
                return func(self, *args)
            else:
                return self.sendCommand(530)
        return _deco

    def fileProperty(self, direntry):
        """
        return information from given file, like this "-rw-r--r-- 1 User Group 312 Aug 1 2014 filename"
        """
        st = direntry.stat()
        fileMessage = []

        def _getFileMode():
            modes = [
                stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR,
                stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP,
                stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH,
            ]
            mode = st.st_mode
            fullmode = ""
            fullmode += direntry.is_dir() and "d" or "-"

            for i in range(9):
                fullmode += bool(mode & modes[i]) and "rwxrwxrwx"[i] or "-"
            return fullmode

        def _getFilesNumber():
            return str(st.st_nlink)

        def _getUser():
            return pwd.getpwuid(st.st_uid).pw_name

        def _getGroup():
            return grp.getgrgid(st.st_gid).gr_name

        def _getSize():
            return str(st.st_size)

        def _getLastTime():
            return time.strftime("%b %d %H:%M", time.gmtime(st.st_mtime))
        for func in ("_getFileMode()", "_getFilesNumber()", "_getUser()", "_getGroup()", "_getSize()", "_getLastTime()"):
            fileMessage.append(eval(func))
        fileMessage.append(direntry.name)
        return " ".join(fileMessage)

    def sendCommand(self, code, arg: str = None):
        result = self.codes_rep.get_code_rep(code)
        if arg:
            result += " " + arg
        result += "\n"
        return result.encode("utf-8")

    @ftp_config
    def startDataSock(self):
        if self.pasv_mode:
            self.dataSock, self.dataAddress = self.serverSock.accept()

    @ftp_config
    def stopDataSock(self, abort=False):
        try:
            if self.pasv_mode:
                if abort:
                    self.dataSock.shutdown(socket.SHUT_RDWR)
                self.dataSock.close()
                self.serverSock.close()
        except OSError:
            return

    class Clients:
        def __init__(self, conn, handle):
            self.queue = queue.Queue()
            self.conn = conn
            self.handle = handle

    class Codes_rep:
        def __init__(self):
            self.codes_rep_dict = dict()
            self.initial()

        def get_code_rep(self, code):
            return str(code)+":"+self.codes_rep_dict.get(code, "code invalide")

        def set_code_rep(self, reps):
            for key, value in reps.items():
                self.codes_rep_dict.update({key: value})

        def del_code_rep(self, code):
            return self.codes_rep_dict.pop(code, "code introuvable")

        def initial(self):
            reps = {
                100: "L'action demandee est lancee, attendre une autre reponse avant de proceder a une nouvelle commande.",
                110: "Resynchronisation des marqueurs entre le client et le serveur.",
                120: "Service pret dans nnn minutes.",
                125: "Connexion etablie, transfert en cours de demarrage.",
                150: "Statut du fichier ok ; Ouverture de la connexion en cours.",
                200: "Action demandee accomplie avec succes.",
                202: "Commande non prise en charge par ce site.",
                211: "Statut du systeme, ou reponse d’aide du systeme.",
                212: "Statut de repertoire.",
                213: "Statut de fichier.",
                214: "Message d'aide sur l'utilisation du serveur ou la signification d'une commande particuliere non-standard. Cette reponse est uniquement utile a un utilisateur humain.",
                215: "Type NAME du systeme.",
                220: "Service pret pour un nouvel utilisateur.",
                221: "Deconnexion.",
                225: "Connexion ouverte, aucun transfert de donnees en cours.",
                226: "Transfert termine avec succes, fermeture de la connexion.",
                227: "Mode passif.",
                228: "Mode passif long.",
                229: "Mode passif etendu.",
                230: "Authentification reussie.",
                231: "Utilisateur deconnecte. Fin de service.",
                232: "Commande de deconnexion enregistree. S'effectuera a la fin du transfert.",
                250: "Action sur le fichier executee avec succes.",
                257: "PATHNAME cree.",
                300: "La commande a ete acceptee, mais l'action demandee est en attente de plus amples informations.",
                331: "Utilisateur reconnu. En attente du mot de passe.",
                332: "Besoin d'un compte de connexion.",
                350: "Requete en attente d’informations complementaires.",
                400: "La commande n'a pas ete acceptee et l'action demandee n'a pas eu lieu, mais l'erreur est temporaire et l'action peut etre demandee a nouveau.",
                421: "Timeout",
                425: "Impossible d'etablir une connexion de donnees.",
                426: "Connexion fermee ; transfert abandonne.",
                430: "Identifiant ou mot de passe incorrect",
                434: "Hôte demande indisponible.",
                450: "Le fichier distant n'est pas disponible",
                451: "Action requise arretee : Erreur locale dans le traitement.",
                452: "Action requise arretee : Espace de stockage insuffisant ou fichier indisponible.",
                500: "Erreur de syntaxe ; commande non reconnue et l'action demandee n'a pu s'effectuer.",
                501: "Erreur de syntaxe dans les parametres ou les arguments.",
                502: "Commande non implementee.",
                503: "Mauvaise sequence de commande",
                504: "Commande non implementee pour ces parametres",
                530: "Connexion non etablie",
                532: "Besoin d'un compte pour charger des fichiers.",
                550: "Requete non executee : Fichier indisponible (ex., fichier introuvable, pas d'acces).",
                551: "Requete arretee : Type de la page inconnu.",
                552: "Requete arretee : Allocation memoire insuffisante.",
                553: "Action non effectuee. Nom de fichier non autorise."
            }
            self.set_code_rep(reps)

    class Cmds_list:
        def __init__(self):
            self.cmds_dict = dict()
            self.initial()

        def get_cmd(self, cmd):
            return str(cmd)+":"+self.cmds_dict.get(cmd, "command invalide")

        def set_cmd(self, cmds):
            for key, value in cmds.items():
                self.cmds_dict.update({key: value})

        def del_code_rep(self, cmd):
            return self.cmds_dict.pop(cmd, "command introuvable")

        def initial(self):
            cmds = {
                "ABOR": "Annuler un transfert.",
                "ACCT": "Information du compte.",
                "ADAT": "Authentification/Donnees de securite.",
                "ALLO": "Allouer assez d'espace disque pour recevoir un fichier.",
                "APPE": "Ajouter.",
                "AUTH": "Authentification/Mecanisme de securite.",
                "CCC": "Effacer le canal de commande.",
                "CDUP": "Transformer en repertoire parent.",
                "CONF": "Commande de protection de confidentialite",
                "CWD": "Changer le repertoire de travail.",
                "DELE": "Supprimer un fichier.",
                "ENC": "Canal de protection de la confidentialite.",
                "EPRT": "Specifie et definit les adresse et port par lesquels la connexion s'etablit.",
                "EPSV": "Entrer en mode passif etendu.",
                "FEAT": "Liste les fonctions supportees par le serveur en plus de ceux inclus dans la RFC 959.",
                "HELP": "Affiche l'aide d'une commande specifique ou l'aide globale.",
                "LANG": "Langue",
                "LIST": "Affiche les informations d'un fichier ou d'un repertoire specifique, ou du repertoire courant.",
                "LPRT": "Specifie et definit une longue adresse et le port par lesquels la connexion s'etablit.",
                "LPSV": "Se connecter en mode passif prolonge.",
                "MDTM": "Affiche la date de derniere modification d'un fichier.",
                "MIC": "Commande de protection d'integrite.",
                "MKD": "Creer un repertoire.",
                "MLSD": "Afficher la liste du contenu d'un repertoire.",
                "MLST": "Fournit des donnees sur l'objet nomme exactement sur la ligne de commande, et pas d'autres.",
                "MODE": "Definir le mode de transfert(Stream, Block, or Compressed).",
                "NLST": "Affiche la liste des noms des fichiers d'un repertoire.",
                "NOOP": "Aucune operation(Paquet factice souvent utilise pour maintenir la connexion).",
                "OPTS": "Selection d'options.",
                "PASS": "Mot de passe.",
                "PASV": "Connexion en mode passif.",
                "PBSZ": "Protection de la taille du Buffer.",
                "PORT": "Specifier une adresse et un port de connexion.",
                "PROT": "Niveau de canal de protection de donnees.",
                "PWD": "Afficher le repertoire de travail actuel sur la machine distante.",
                "QUIT": "Deconnecter.",
                "REIN": "Reinitialiser la connexion.",
                "REST": "Recommencer le transfert a partir d'un point specifique.",
                "RETR": "Recuperer la copie d'un fichier.",
                "RMD": "Supprimer un repertoire.",
                "RNFR": "Fichier a renommer(rename from)",
                "RNTO": "Renommer en(rename to)",
                "SITE": "Envoie une commande specifique de site au serveur distant.",
                "SIZE": "Affiche la taille d'un fichier.",
                "SMNT": "Monter la structure d'un fichier.",
                "STAT": "Affiche le statut courant.",
                "STOR": "Accepter les donnees et les enregistrer dans un fichier sur le serveur.",
                "STOU": "Enregistrer les fichiers de façon unique.",
                "STRU": "Definir la structure de transfert de fichier.",
                "SYST": "Afficher le type systeme.",
                "TYPE": "Definir le mode de transfert(ASCII/Binary).",
                "USER": "Nom d'utilisateur, identifiant.",
                "XCUP": "Transformer en parent du repertoire courant.",
                "XMKD": "Creer un repertoire",
                "XPWD": "Afficher le repertoire de travail courant.",
                "XRMD": "Supprimer un repertoire",
                "XSEM": "Envoyer un courrier electronique en cas d'erreur.",
                "XSEN": "Envoyer au terminal"
            }
            self.set_cmd(cmds)

    #---------------------------------#
    ## Ftp serveur functions de base ##
    #---------------------------------#

    def start(self):
        self.sock.bind(self.addr)
        self.sock.listen(self.client_size)
        self.sock.setblocking(False)
        log(obj="Bienvenue le serveur Ftp Junxi!",
            description="Listen on %s: %s" % self.sock.getsockname())

        key = self.selector.register(
            self.sock, selectors.EVENT_READ, self._accept)

        threading.Thread(target=self._run, name="run", daemon=True).start()

    def _run(self, poll_interval=0.5):
        self.__stop_request.clear()
        try:
            while not self.__stop_request.is_set():
                if self.__is_stop:
                    break
                events = self.selector.select(poll_interval)
                for key, mask in events:
                    if callable(key.data):
                        callback = key.data
                    else:
                        callback = key.data.handle
                    callback(key.fileobj, mask)
        finally:
            self.__is_stop = False
            self.__stop_request.set()

    def stop(self):
        self.__is_stop = True
        self.__stop_request.wait()
        self.fobjs = []
        for fobj, key in self.selector.get_map().items():
            key.fileobj.close()
            self.fobjs.append(fobj)

        for x in self.fobjs:
            self.selector.unregister(x)
        self.selector.close()

    def _accept(self, sock: socket.socket, mask):
        conn, client_addr = self.sock.accept()
        self.clients[client_addr] = self.Clients(conn, self._handle)
        conn.setblocking(False)
        log("New Client", "vient de %s: %s" % client_addr)
        self.clients[client_addr].queue.put(self.sendWelcome())

        self.selector.register(conn, selectors.EVENT_READ |
                               selectors.EVENT_WRITE, self.clients[client_addr])

    def _handle(self, conn, mask):
        try:
            remote = conn.getpeername()
            client = self.clients[remote]
        except OSError:
            return

        if mask & selectors.EVENT_READ == selectors.EVENT_READ:
            """
            receive commands from client and execute commands
            """
            try:
                data = conn.recv(1024).decode().strip()
            except ConnectionResetError:
                return

            if data != "" or data != None:
                log("Received data", data)
                try:
                    cmd, arg = data.split(" ", 1)
                except ValueError:
                    cmd, arg = data, None
                func = self.cmds_list.get_cmd(cmd.upper())
                if func.split(":")[1] == "command invalide":
                    log("Receive", "command invalide")
                    client.queue.put(self.sendCommand(500))
                else:
                    method = getattr(self, cmd.upper(), None)
                    try:
                        if method:
                            if cmd.upper() in ["LIST", "RETR", "STOR"]:
                                client.queue.put(method(conn, arg))
                            else:
                                client.queue.put(method(arg))
                        else:
                            client.queue.put(self.sendCommand(500))
                            log("Receive", "command non prise en charge")
                    except (OSError, ConnectionResetError):
                        self.ABOR()

        if mask & selectors.EVENT_WRITE == selectors.EVENT_WRITE:

            while not client.queue.empty():
                msg = client.queue.get()
                try:
                    conn.send(msg)
                except OSError:
                    return

    #------------------------------#
    ## Ftp services and functions ##
    #------------------------------#

    #-------------------------#
    ## Connexion/déconnexion ##
    #-------------------------#

    def USER(self, user):
        if not user:
            self.username = "anonyme"
            log("USER", self.username)
            self.authenticated = True
            return self.sendCommand(230, "Sur user anonyme.")
        else:
            self.username = user
            log("USER", self.username)
            return self.sendCommand(331)

    def PASS(self, passwd):
        log("PASS", passwd)
        if not self.username:
            return self.sendCommand(503)
        if self.username != "anonyme":
            if not passwd:
                return self.sendCommand(501)
            else:
                self.passwd = passwd
                self.authenticated = True
                return self.sendCommand(230)
        else:
            return "Aucun mot de passe requis sur user anonyme\n".encode("utf-8")

    def NOOP(self, arg):
        return self.sendCommand(200)

    @ftp_config
    def HELP(self, arg):
        return self.sendCommand(214, repr(self.cmds_list.cmds_dict))

    @ftp_config
    def QUIT(self, arg):
        self.authenticated = False
        return self.sendCommand(221)

    #---------------------------------#
    ## Naviguer dans les répertoires ##
    #---------------------------------#

    @ftp_config
    def PASV(self, arg):
        self.pasv_mode = True
        self.serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serverSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.serverSock.bind((self.addr[0], 0))
        self.serverSock.listen(self.client_size)
        pasv_addr, pasv_port = self.serverSock.getsockname()
        return self.sendCommand(227, "Listen at (%s,%d,%d)." % (",".join(pasv_addr.split(".")), pasv_port >> 8 & 0xFF, pasv_port & 0xFF))

    @ftp_config
    def LIST(self, conn, dirpath):
        if not dirpath:
            pathname = self.pathname
        elif dirpath.startswith(os.sep):
            pathname = os.path.abspath(dirpath)
        else:
            pathname = os.path.abspath(os.path.join(self.pathname, dirpath))
        if not os.path.exists(pathname):
            return self.sendCommand(550)
        else:
            conn.send(self.sendCommand(150))
            self.startDataSock()
            with os.scandir(pathname) as it:
                for entry in it:
                    if entry.name.startswith("."):
                        continue
                    try:
                        self.dataSock.send(
                            (self.fileProperty(entry) + "\n").encode("utf-8"))
                    except Exception:
                        continue
            self.stopDataSock()
        return self.sendCommand(226)

    @ftp_config
    def TYPE(self, arg):
        if arg == "I":
            self.mode_is_Ascii = False
        elif arg == "A":
            self.mode_is_Ascii = True
        else:
            return self.sendCommand(501)
        return self.sendCommand(200, "Sur %s mode." % ("Ascii" if self.mode_is_Ascii else "Binary"))

    @ftp_config
    def SYST(self, arg):
        return self.sendCommand(215, "%s type." % sys.platform)

    @ftp_config
    def PWD(self, arg):
        return self.sendCommand(257, "'" + self.pathname + "'")

    @ftp_config
    def CDUP(self, arg):
        self.pathname = os.path.dirname(self.pathname)
        if self.pathname == "" or None:
            self.pathname = "/"
        return self.sendCommand(200)

    @ftp_config
    def CWD(self, dirpath):
        pathname = dirpath.startswith(
            os.sep) and dirpath or os.path.join(self.pathname, dirpath)
        if not os.path.exists(pathname) or not os.path.isdir(pathname):
            return self.sendCommand(550)
        self.pathname = pathname
        return self.sendCommand(250)

    #-------------------------------------#
    ## Envoyer/recevoir des fichiers     ##
    #-------------------------------------#

    @ftp_config
    def RETR(self, conn, filename):
        pathname = os.path.join(self.pathname, filename)
        if not os.path.exists(pathname):
            return self.sendCommand(550)
        try:
            if not self.mode_is_Ascii:
                file = open(pathname, "rb")
            else:
                file = open(pathname, "r")
        except OSError as err:
            log("RETR", err)

        conn.send(self.sendCommand(150))
        if self.rest:
            file.seek(self.pos)
            self.rest = False

        self.startDataSock()
        while True:
            data = file.read(1024)
            if not data:
                break
            self.dataSock.send(data.encode("utf-8"))
        file.close()
        self.stopDataSock()
        return self.sendCommand(226)

    @ftp_config
    def REST(self, pos):
        self.pos = int(pos)
        self.rest = True
        return self.sendCommand(350)

    @ftp_config
    def STOR(self, conn, filename):
        pathname = os.path.join(self.pathname, filename)
        try:
            if not self.mode_is_Ascii:
                file = open(pathname, "wb")
            else:
                file = open(pathname, "w")
        except OSError as err:
            log("STOR", err)

        conn.send(self.sendCommand(150))
        if self.rest:
            file.seek(self.pos)
            self.rest = False

        self.startDataSock()
        while True:
            data = self.dataSock.recv(1024)
            if not data:
                break
            file.write(data.decode("utf-8"))
        file.close()
        self.stopDataSock()
        return self.sendCommand(226)

    @ftp_config
    def APPE(self, filename):
        pathname = os.path.join(self.pathname, filename)
        if not os.path.exists(pathname):
            if not self.mode_is_Ascii:
                file = open(pathname, "wb")
            else:
                file = open(pathname, "w")
            while True:
                data = self.dataSock.recv(1024)
                if not data:
                    break
                file.write(data.decode("utf-8"))
        else:
            n = 1
            while os.path.exists(pathname):
                filename, extname = os.path.splitext(pathname)
                pathname = filename + "(%s)" % n + extname
                n += 1

            if not self.mode_is_Ascii:
                file = open(pathname, "wb")
            else:
                file = open(pathname, "w")
            while True:
                data = self.dataSock.recv(1024)
                if not data:
                    break
                file.write(data.decode("utf-8"))
        file.close()
        self.stopDataSock()
        return self.sendCommand(226)

    @ftp_config
    def ABOR(self, arg):
        self.stopDataSock(True)
        return self.sendCommand(226)

    #---------------------------#
    ## Manipulation de fichier ##
    #---------------------------#

    @ftp_config
    def DELE(self, filename):
        pathname = os.path.join(self.pathname, filename)
        if not os.path.exists(pathname):
            return self.sendCommand(550)

        elif not self.allow_delete:
            return self.sendCommand(450)

        else:
            os.remove(pathname)
            return self.sendCommand(250)

    @ftp_config
    def MKD(self, dirname):
        pathname = os.path.join(self.pathname, dirname)

        try:
            os.mkdir(pathname)
            return self.sendCommand(257)
        except OSError:
            return self.sendCommand(550, "'%s' already exists." % pathname)

    @ftp_config
    def RMD(self, dirname):
        pathname = os.path.join(self.pathname, dirname)
        if not self.allow_delete:
            return self.sendCommand(450)

        elif not os.path.exists(pathname):
            return self.sendCommand(550)

        else:
            shutil.rmtree(pathname)
            return self.sendCommand(250)

    @ftp_config
    def RNFR(self, filename):
        pathname = os.path.join(self.pathname, filename)
        if not os.path.exists(pathname):
            return self.sendCommand(550)
        else:
            self.oldname = pathname
            return self.sendCommand(350)

    @ftp_config
    def RNTO(self, filename):
        pathname = os.path.join(self.pathname, filename)
        if os.path.exists(pathname):
            return self.sendCommand(550)
        else:
            try:
                os.rename(self.oldname, pathname)
                return self.sendCommand(250)
            except OSError as err:
                log("RNTO", err)
                return self.sendCommand(553)

    #----------------------------------------#
    ## Ftp serveur functions supplémentaire ##
    #----------------------------------------#

    def sendWelcome(self):
        """
        when connection created with client will send a welcome message to the client
        """
        return self.sendCommand(220)

    @ftp_config
    def REIN(self, arg):
        self.initial()
        return self.sendCommand(220)

def main():
    fs = FTPServer()
    fs.start()
    e = threading.Event()
    while not e.wait(1):
        cmd = input(
            ">>>> Pour fermer le serveur, veuillez taper q.\n").lower().strip()
        if cmd == "q":
            fs.stop()
            e.wait(3)
            break


if __name__ == "__main__":

    print(str_color("Faire reference a", 36) +
          str_color("https://github.com/jacklam718/ftp/", 34))
    main()
