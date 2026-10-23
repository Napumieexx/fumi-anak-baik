import random
import time
import discord
from discord.ext import commands

QUESTION_BANK = [
    {"category":"receh","question":"Kalau ada 10 ikan di akuarium, 2 tenggelam, tinggal berapa ikan?","options":["8 ikan","10 ikan","2 ikan","Tidak ada"],"answer":1,"explanation":"Ikan hidup di air, jadi kata 'tenggelam' adalah jebakannya. Semua ikan masih ada di akuarium."},
    {"category":"receh","question":"Apa yang punya banyak gigi tapi tidak pernah makan?","options":["Buaya","Sisir","Hiu","Garpu"],"answer":1,"explanation":"Sisir punya gigi untuk merapikan rambut, bukan untuk makan."},
    {"category":"receh","question":"Ayam jantan bertelur di atas genteng. Telurnya jatuh ke mana?","options":["Ke kiri","Ke kanan","Ke halaman","Ayam jantan tidak bertelur"],"answer":3,"explanation":"Ayam jantan tidak bertelur. Fokus pertanyaan ini sengaja dialihkan ke genteng."},
    {"category":"receh","question":"Kenapa kalender seolah-olah selalu sibuk?","options":["Banyak tanggal","Dikejar waktu","Tidak bisa tidur","Suka matematika"],"answer":1,"explanation":"Ini permainan kata: kalender berisi tanggal dan jadwal, seolah dikejar waktu."},
    {"category":"logika","question":"Kamu menyalip pelari di posisi kedua. Sekarang kamu berada di posisi berapa?","options":["Pertama","Kedua","Ketiga","Terakhir"],"answer":1,"explanation":"Kamu mengambil posisi pelari yang kamu salip, yaitu posisi kedua."},
    {"category":"logika","question":"Satu keluarga punya 4 anak perempuan. Setiap anak perempuan punya satu saudara laki-laki yang sama. Berapa jumlah minimal anak mereka?","options":["4","5","8","9"],"answer":1,"explanation":"Empat anak perempuan berbagi satu saudara laki-laki yang sama, jadi totalnya lima anak."},
    {"category":"logika","question":"Jam menunjukkan pukul 3.00 tepat. Berapa sudut terkecil antara jarum jam dan menit?","options":["45°","60°","90°","180°"],"answer":2,"explanation":"Jarum menit berada di angka 12 dan jarum jam di angka 3, sehingga sudutnya 90°."},
    {"category":"trivia","question":"Apa semboyan nasional Indonesia?","options":["Tut Wuri Handayani","Bhinneka Tunggal Ika","Ing Ngarsa Sung Tuladha","Jalesveva Jayamahe"],"answer":1,"explanation":"Bhinneka Tunggal Ika adalah semboyan nasional Indonesia."},
    {"category":"trivia","question":"Planet apa yang terkenal dengan sistem cincinnya yang mencolok?","options":["Mars","Venus","Saturnus","Merkurius"],"answer":2,"explanation":"Saturnus dikenal dengan sistem cincin yang besar dan terang."},
    {"category":"trivia","question":"Mamalia yang dapat terbang aktif dengan kepakan sayap adalah...","options":["Tupai terbang","Kelelawar","Lemur","Elang"],"answer":1,"explanation":"Kelelawar adalah mamalia yang bisa terbang aktif; tupai terbang melayang."},
    {"category":"trivia","question":"Dalam catur standar, bidak mana yang bergerak diagonal?","options":["Benteng","Kuda","Gajah","Raja"],"answer":2,"explanation":"Gajah bergerak diagonal sepanjang jalur yang tidak terhalang."},

    # Pertanyaan tambahan original untuk memperbanyak variasi kuis
    {"category":"receh","question":"Kalau nasi sudah menjadi bubur, apa yang paling masuk akal dilakukan?","options":["Masukkan kembali ke sawah","Dimakan atau diolah jadi bubur ayam","Disetrika","Dijadikan payung"],"answer":1,"explanation":"Nasi yang sudah menjadi bubur bisa dimakan atau diberi topping. Tidak bisa dikembalikan menjadi nasi utuh."},
    {"category":"receh","question":"Benda apa yang makin sering dipakai justru makin pendek?","options":["Penggaris","Pensil","Meja","Jendela"],"answer":1,"explanation":"Pensil akan makin pendek saat diraut dan digunakan."},
    {"category":"receh","question":"Kalau kamu punya satu korek api dan masuk ke ruangan gelap berisi lilin, lampu minyak, dan kompor, apa yang dinyalakan pertama?","options":["Lilin","Lampu minyak","Kompor","Korek apinya"],"answer":3,"explanation":"Korek api harus dinyalakan terlebih dahulu sebelum bisa menyalakan benda lain."},
    {"category":"receh","question":"Apa yang selalu naik tetapi tidak pernah turun?","options":["Harga semua barang","Umur","Balon","Lift"],"answer":1,"explanation":"Umur seseorang bertambah seiring waktu."},
    {"category":"receh","question":"Kenapa buku matematika sering terlihat sedih?","options":["Kehujanan","Punya banyak masalah","Kehilangan sampul","Tidak punya teman"],"answer":1,"explanation":"Ini permainan kata: buku matematika berisi banyak soal atau masalah."},
    {"category":"receh","question":"Kalau ada 5 apel lalu kamu mengambil 2, berapa apel yang kamu punya?","options":["3","2","5","7"],"answer":1,"explanation":"Kamu mengambil 2 apel, jadi 2 apel itulah yang kamu punya."},
    {"category":"receh","question":"Apa yang punya leher tetapi tidak punya kepala?","options":["Jerapah","Botol","Burung","Kuda"],"answer":1,"explanation":"Botol memiliki bagian yang disebut leher botol."},
    {"category":"logika","question":"Dua ayah dan dua anak pergi memancing. Mereka mendapat tiga ikan, dan masing-masing mendapat satu. Bagaimana bisa?","options":["Ada ikan bonus","Mereka sebenarnya tiga orang: kakek, ayah, dan anak","Satu orang tidak makan ikan","Soalnya salah"],"answer":1,"explanation":"Ada tiga orang: seorang kakek, anaknya yang juga ayah, dan cucunya."},
    {"category":"logika","question":"Sebuah kereta listrik bergerak ke utara. Angin bertiup ke selatan. Ke mana arah asap kereta?","options":["Utara","Selatan","Barat","Tidak ada asap dari kereta listrik"],"answer":3,"explanation":"Kereta listrik tidak menghasilkan asap seperti lokomotif berbahan bakar."},
    {"category":"logika","question":"Ada 12 bulan dalam setahun. Berapa bulan yang memiliki setidaknya 28 hari?","options":["1","2","6","12"],"answer":3,"explanation":"Semua bulan memiliki setidaknya 28 hari."},
    {"category":"logika","question":"Kamu melihat 3 apel dan mengambil 1. Berapa apel yang kamu ambil?","options":["1","2","3","0"],"answer":0,"explanation":"Pertanyaannya menanyakan berapa yang kamu ambil, bukan berapa yang tersisa."},
    {"category":"logika","question":"Sebuah ruangan memiliki empat sudut. Di setiap sudut ada seekor kucing. Setiap kucing melihat tiga kucing lain. Ada berapa kucing?","options":["4","8","12","16"],"answer":0,"explanation":"Ada empat kucing, satu di setiap sudut, dan masing-masing melihat tiga kucing lainnya."},
    {"category":"logika","question":"Jika 5 mesin membuat 5 barang dalam 5 menit, berapa lama 100 mesin membuat 100 barang dengan kecepatan sama?","options":["5 menit","20 menit","100 menit","500 menit"],"answer":0,"explanation":"Setiap mesin membuat satu barang dalam lima menit, jadi 100 mesin dapat membuat 100 barang dalam lima menit."},
    {"category":"trivia","question":"Apa nama proses tumbuhan membuat makanan menggunakan cahaya matahari?","options":["Respirasi","Fotosintesis","Fermentasi","Evaporasi"],"answer":1,"explanation":"Fotosintesis menggunakan energi cahaya untuk membantu tumbuhan membuat makanan."},
    {"category":"trivia","question":"Benua terbesar di dunia berdasarkan luas wilayah adalah...","options":["Afrika","Eropa","Asia","Amerika Selatan"],"answer":2,"explanation":"Asia adalah benua terbesar berdasarkan luas wilayah."},
    {"category":"trivia","question":"Organ tubuh manusia yang memompa darah ke seluruh tubuh adalah...","options":["Paru-paru","Lambung","Jantung","Ginjal"],"answer":2,"explanation":"Jantung memompa darah melalui sistem peredaran darah."},
    {"category":"trivia","question":"Berapa jumlah sisi pada segi enam?","options":["5","6","7","8"],"answer":1,"explanation":"Segi enam memiliki enam sisi."},
    {"category":"trivia","question":"Gas apa yang paling banyak terdapat di atmosfer Bumi?","options":["Oksigen","Karbon dioksida","Nitrogen","Hidrogen"],"answer":2,"explanation":"Atmosfer Bumi terdiri terutama dari nitrogen, sekitar 78 persen."},
    {"category":"trivia","question":"Hewan yang dikenal mengalami metamorfosis dari ulat menjadi dewasa adalah...","options":["Kupu-kupu","Kucing","Ayam","Kuda"],"answer":0,"explanation":"Kupu-kupu melalui tahap telur, ulat, kepompong, lalu kupu-kupu dewasa."},
    {"category":"trivia","question":"Alat untuk mengukur suhu disebut...","options":["Barometer","Termometer","Speedometer","Altimeter"],"answer":1,"explanation":"Termometer digunakan untuk mengukur suhu."},
    {"category":"trivia","question":"Samudra terluas di Bumi adalah...","options":["Samudra Hindia","Samudra Atlantik","Samudra Arktik","Samudra Pasifik"],"answer":3,"explanation":"Samudra Pasifik adalah samudra terluas di Bumi."},
    {"category":"trivia","question":"Berapa jumlah warna yang biasanya disebut dalam pelangi menurut pembagian tradisional?","options":["5","6","7","8"],"answer":2,"explanation":"Pembagian tradisional menyebut tujuh warna pelangi."},
    {"category":"trivia","question":"Bahan utama yang digunakan lebah untuk membuat madu adalah...","options":["Nektar bunga","Pasir","Daun kering","Air laut"],"answer":0,"explanation":"Lebah mengumpulkan nektar bunga dan mengolahnya menjadi madu."},
    {"category":"trivia","question":"Satuan dasar untuk mengukur kuat arus listrik adalah...","options":["Volt","Watt","Ampere","Ohm"],"answer":2,"explanation":"Arus listrik diukur dalam ampere."},
    {"category":"receh","question":"Apa yang bisa pecah meskipun tidak pernah jatuh ke lantai?","options":["Janji","Batu","Piring","Gelas"],"answer":0,"explanation":"Janji bisa dilanggar atau 'dipecahkan' tanpa benda jatuh."},
    {"category":"receh","question":"Kalau pintu terbuka, apa yang biasanya perlu dilakukan agar tertutup?","options":["Ditiup sampai terbang","Menutup pintunya","Memanggil tukang kebun","Mematikan lampu"],"answer":1,"explanation":"Jawabannya sengaja sederhana: tutup pintunya."},
    {"category":"logika","question":"Sebuah keluarga memiliki 3 putra. Setiap putra punya satu saudara perempuan yang sama. Berapa jumlah minimal anak?","options":["3","4","6","9"],"answer":1,"explanation":"Ketiga putra memiliki satu saudara perempuan yang sama, jadi total empat anak."},
    {"category":"trivia","question":"Bahasa pemrograman yang namanya sama dengan jenis ular adalah...","options":["Java","Python","Ruby","Swift"],"answer":1,"explanation":"Python adalah bahasa pemrograman yang namanya juga berarti jenis ular."},
    {"category":"trivia","question":"Berapakah hasil perkalian 9 × 8?","options":["63","72","81","89"],"answer":1,"explanation":"9 dikali 8 sama dengan 72."},
    {"category":"logika","question":"Jika hari ini hari Selasa, hari apa 10 hari lagi?","options":["Kamis","Jumat","Sabtu","Minggu"],"answer":1,"explanation":"Tujuh hari kemudian tetap Selasa; tiga hari tambahan menjadi Jumat."},
]

CATEGORY_LABELS = {"campur":"Campuran","receh":"Tebak-tebakan receh","logika":"Logika menjebak","trivia":"Trivia menarik"}
scores = {}


class QuizView(discord.ui.View):
    def __init__(self, question, participant_ids, seconds=20):
        super().__init__(timeout=seconds)
        self.question = question
        self.participant_ids = participant_ids
        self.answered = set()
        self.finished = False
        self.ends_at = time.monotonic() + seconds
        self.message = None
        for i, button in enumerate(self.children):
            button.label = f"{'ABCD'[i]}. {question['options'][i]}"

    async def choose(self, interaction, index):
        if self.finished:
            await interaction.response.send_message("Ronde ini sudah selesai.", ephemeral=True)
            return
        if interaction.user.id not in self.participant_ids:
            await interaction.response.send_message("Kamu belum terdaftar sebagai anggota server untuk ronde ini.", ephemeral=True)
            return
        if interaction.user.id in self.answered:
            await interaction.response.send_message("Kamu sudah menjawab ronde ini.", ephemeral=True)
            return

        self.answered.add(interaction.user.id)
        key = (interaction.guild_id or 0, interaction.user.id)
        if index == self.question["answer"]:
            scores[key] = scores.get(key, 0) + 10
            feedback = "✅ Benar! +10 poin."
        else:
            feedback = "❌ Belum tepat. Coba lagi di ronde berikutnya."
        await interaction.response.send_message(feedback, ephemeral=True)
        if self.answered >= self.participant_ids:
            await self.finish_round()

    async def finish_round(self):
        if self.finished:
            return
        self.finished = True
        for button in self.children:
            button.disabled = True
        q = self.question
        content = f"⏱️ **Jawaban:** {q['options'][q['answer']]}\n{q['explanation']}\n\nJawaban benar mendapat +10 poin."
        if self.message:
            try:
                await self.message.edit(content=content, embed=None, view=self)
            except discord.HTTPException:
                pass

    async def on_timeout(self):
        await self.finish_round()

    @discord.ui.button(label="A", style=discord.ButtonStyle.secondary, row=0)
    async def a(self, interaction, button): await self.choose(interaction, 0)
    @discord.ui.button(label="B", style=discord.ButtonStyle.secondary, row=1)
    async def b(self, interaction, button): await self.choose(interaction, 1)
    @discord.ui.button(label="C", style=discord.ButtonStyle.secondary, row=2)
    async def c(self, interaction, button): await self.choose(interaction, 2)
    @discord.ui.button(label="D", style=discord.ButtonStyle.secondary, row=3)
    async def d(self, interaction, button): await self.choose(interaction, 3)


def setup_quiz(bot):
    active_guilds = set()

    @bot.command(name="kuis", aliases=["quiz", "kuiscepat"])
    async def kuis(ctx, kategori="campur"):
        if not ctx.guild:
            await ctx.send("Kuis hanya bisa dimulai di server.")
            return
        kategori = kategori.lower()
        if kategori not in CATEGORY_LABELS:
            await ctx.send("Kategori: `campur`, `receh`, `logika`, atau `trivia`.")
            return
        if ctx.guild.id in active_guilds:
            await ctx.send("Masih ada ronde kuis aktif di server ini. Tunggu sampai selesai.")
            return
        pool = [q for q in QUESTION_BANK if kategori == "campur" or q["category"] == kategori]
        q = random.choice(pool)
        active_guilds.add(ctx.guild.id)
        try:
            embed = discord.Embed(title=f"⚡ Kuis Cepat Fumi — {CATEGORY_LABELS[kategori]}", description=q["question"], color=discord.Color.blurple())
            embed.set_footer(text="Pilih A, B, C, atau D • 20 detik • Jawaban benar +10 poin")
            participants = {m.id for m in ctx.guild.members if not m.bot}
            participants.add(ctx.author.id)
            view = QuizView(q, participants, seconds=20)
            view.message = await ctx.send(embed=embed, view=view)
            await view.wait()
        finally:
            active_guilds.discard(ctx.guild.id)

    @bot.command(name="poin", aliases=["skorkuis"])
    async def poin(ctx, anggota: discord.Member = None):
        member = anggota or ctx.author
        score = scores.get((ctx.guild.id if ctx.guild else 0, member.id), 0)
        await ctx.send(f"🏅 {member.mention} punya **{score} poin kuis**.")

    @bot.command(name="leaderboard", aliases=["lb", "peringkat"])
    async def leaderboard(ctx):
        gid = ctx.guild.id if ctx.guild else 0
        rows = [(uid, score) for (server, uid), score in scores.items() if server == gid]
        rows.sort(key=lambda x: x[1], reverse=True)
        if not rows:
            await ctx.send("Belum ada poin. Mulai dengan `!kuis`!")
            return
        lines = []
        for rank, (uid, score) in enumerate(rows[:10], 1):
            member = ctx.guild.get_member(uid) if ctx.guild else None
            name = member.display_name if member else f"User {uid}"
            lines.append(f"**{rank}.** {name} — {score} poin")
        await ctx.send("🏆 **Leaderboard Kuis Fumi**\n" + "\n".join(lines))

    @bot.command(name="kuishelp", aliases=["bantukuis"])
    async def kuishelp(ctx):
        await ctx.send(
            "**⚡ Kuis Cepat Fumi**\n"
            "`!kuis` — kategori campuran\n"
            "`!kuis receh` — tebak-tebakan absurd\n"
            "`!kuis logika` — pertanyaan jebakan logika\n"
            "`!kuis trivia` — pengetahuan umum\n"
            "`!poin` — cek poin sendiri\n"
            "`!leaderboard` — peringkat 10 besar"
        )
