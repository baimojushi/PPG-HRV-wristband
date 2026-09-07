from __future__ import annotations

from dataclasses import asdict, dataclass
from html import escape


@dataclass(frozen=True, slots=True)
class LiteratureSource:
    source_id: int
    authors: str
    title: str
    year: int
    journal: str
    url: str
    study_detail: str
    finding_detail: str

    def to_dict(self) -> dict:
        return asdict(self)

    def ui_reference(self) -> str:
        """
        面向 Qt RichText 的短引用。

        [数字] 本身是可点击超链接；
        后面保留文献名和作者，满足 UI 审查可追溯要求。
        """
        return (
            f'<a href="{escape(self.url)}">[{self.source_id}]</a> '
            f'《{escape(self.title)}》 — {escape(self.authors)}'
        )

    def ui_fact_line(self) -> str:
        return (
            f'{escape(self.study_detail)}；'
            f'{escape(self.finding_detail)}。 '
            f'{self.ui_reference()}'
        )


LITERATURE_SOURCES: tuple[LiteratureSource, ...] = (
    LiteratureSource(
        source_id=1,
        authors="Shr-Da Wu, Pei-Chen Lo",
        title=(
            "Inward-attention meditation increases parasympathetic activity: "
            "a study based on heart rate variability"
        ),
        year=2008,
        journal="Biomedical Research",
        url="https://pubmed.ncbi.nlm.nih.gov/18997439/",
        study_detail=(
            "10名有Zen禅修经验者与10名无禅修经验对照，比较内向注意冥想与正常休息"
        ),
        finding_detail=(
            "经验组冥想时LF/HF和LF标准化功率下降、HF标准化功率上升，"
            "并观察到较规则的心率振荡"
        ),
    ),
    LiteratureSource(
        source_id=2,
        authors=(
            "C-K Peng, Isaac C Henry, Joseph E Mietus, Jeffrey M Hausdorff, "
            "Gurucharan Khalsa, Herbert Benson, Ary L Goldberger"
        ),
        title="Heart rate dynamics during three forms of meditation",
        year=2004,
        journal="International Journal of Cardiology",
        url="https://pubmed.ncbi.nlm.nih.gov/15159033/",
        study_detail=(
            "10名有经验冥想者（4女6男，29–55岁，平均42岁）依次完成放松反应、火呼吸和分段呼吸"
        ),
        finding_detail=(
            "放松反应与分段呼吸出现约0.05–0.10 Hz高振幅心率振荡且心率-呼吸相干增强；"
            "火呼吸则平均心率升高、相干下降"
        ),
    ),
    LiteratureSource(
        source_id=3,
        authors=(
            "Jonathan R Krygier, James A J Heathers, Sara Shahrestani, "
            "Maree Abbott, James J Gross, Andrew H Kemp"
        ),
        title=(
            "Mindfulness meditation, well-being, and heart rate variability: "
            "a preliminary investigation into the impact of intensive Vipassana meditation"
        ),
        year=2013,
        journal="International Journal of Psychophysiology",
        url="https://pubmed.ncbi.nlm.nih.gov/23797150/",
        study_detail=(
            "36名首次参加10天S. N. Goenka传统Vipassana密集课程的参与者（16男20女，平均43.8岁）在训练前后各比较5分钟静息与5分钟冥想"
        ),
        finding_detail=(
            "训练前冥想主要表现为lnHF增加；训练后冥想出现HF n.u.增加、"
            "Traube–Hering–Mayer低频成分下降"
        ),
    ),
    LiteratureSource(
        source_id=4,
        authors=(
            "Luis Carlos Delgado-Pastor, Pandelis Perakakis, Pailoor Subramanya, "
            "Shirley Telles, Jaime Vila"
        ),
        title=(
            "Mindfulness (Vipassana) meditation: effects on P3b event-related "
            "potential and heart rate variability"
        ),
        year=2013,
        journal="International Journal of Psychophysiology",
        url="https://pubmed.ncbi.nlm.nih.gov/23892096/",
        study_detail=(
            "10名男性Vipassana经验者（20–61岁，至少2年练习，平均7.5年、每周约15小时）完成30分钟结构化冥想；HRV分析因伪迹排除3人："
            "Anapana 10分钟、Vipassana 15分钟、Metta 5分钟"
        ),
        finding_detail=(
            "LF和HF在Anapana阶段下降、Vipassana阶段上升、Metta阶段再次下降；"
            "Vipassana阶段LF/HF的增加幅度更明显"
        ),
    ),
    LiteratureSource(
        source_id=5,
        authors="Ido Amihai, Maria Kozhevnikov",
        title=(
            "Arousal vs. Relaxation: A Comparison of the Neurophysiological and "
            "Cognitive Correlates of Vajrayana and Theravada Meditative Practices"
        ),
        year=2014,
        journal="PLOS ONE",
        url="https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0102990",
        study_detail=(
            "10名长期Theravada练习者（2女，平均41.4岁、8年经验，泰国Yannawa Temple）与9名长期Vajrayana练习者（1女，平均47.5岁、7.4年经验，尼泊尔Shechen Monastery）"
        ),
        finding_detail=(
            "Theravada Vipassana相对静息HF增加且LF/HF下降；"
            "Vajrayana的Deity与Rig-pa练习则出现HF下降的不同模式"
        ),
    ),
    LiteratureSource(
        source_id=6,
        authors=(
            "Caroline Peressutti, Juan M Martín-González, "
            "Juan M García-Manso, Denkô Mesa"
        ),
        title="Heart rate dynamics in different levels of Zen meditation",
        year=2010,
        journal="International Journal of Cardiology",
        url="https://pubmed.ncbi.nlm.nih.gov/19631997/",
        study_detail=(
            "19名Soto-Zen坐禅练习者（7女12男，平均43.8岁，练习经验2个月–20年），其中4人同步记录呼吸"
        ),
        finding_detail=(
            "研究同时使用频域分析和连续小波变换，观察到呼吸性心律调制随练习经验水平改变"
        ),
    ),
    LiteratureSource(
        source_id=7,
        authors="Harunobu Usui, Yusuke Nishida",
        title=(
            "The very low-frequency band of heart rate variability represents "
            "the slow recovery component after a mental stress task"
        ),
        year=2017,
        journal="PLOS ONE",
        url="https://pubmed.ncbi.nlm.nih.gov/28806776/",
        study_detail=(
            "19名健康年轻受试者先静息10分钟，再完成20分钟Stroop任务，并继续静息恢复120分钟"
        ),
        finding_detail=(
            "任务后HF和LF/HF很快回到基线，而VLF在恢复期持续低于静息水平，呈现更慢的恢复轨迹"
        ),
    ),
    LiteratureSource(
        source_id=8,
        authors="Kang-Ming Chang, Miao-Tien Wu Chueh, Yi-Jung Lai",
        title="Meditation Practice Improves Short-Term Changes in Heart Rate Variability",
        year=2020,
        journal="International Journal of Environmental Research and Public Health",
        url="https://pmc.ncbi.nlm.nih.gov/articles/PMC7142551/",
        study_detail=(
            "Heart Chan研究包含两次90分钟课程实验：第一组45名无冥想经验参与者；第二组27名长期练习者（5男22女、20–68岁），平均练习9年（1–27年）"
        ),
        finding_detail=(
            "研究以课前/课后和一个月重复测量观察HR、HRV与频域指标，"
            "为小时级课程和经验层差异提供纵向研究参照"
        ),
    ),
)


_BY_ID = {
    item.source_id: item
    for item in LITERATURE_SOURCES
}


def get_source(
    source_id: int,
) -> LiteratureSource:
    return _BY_ID[int(source_id)]


def sources_to_dict() -> list[dict]:
    return [
        item.to_dict()
        for item in LITERATURE_SOURCES
    ]


def render_source_facts_html(
    source_ids: list[int] | tuple[int, ...],
) -> str:
    unique: list[int] = []
    for source_id in source_ids:
        value = int(source_id)
        if value not in unique:
            unique.append(value)

    return "<br/>".join(
        get_source(source_id).ui_fact_line()
        for source_id in unique
        if source_id in _BY_ID
    )
