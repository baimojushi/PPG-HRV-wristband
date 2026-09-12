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
    condition_detail: str = ""
    evidence_level: str = "study"
    transfer_note: str = ""

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
        condition = (
            f'；研究情境：{escape(self.condition_detail)}'
            if self.condition_detail
            else ''
        )
        return (
            f'研究对象：{escape(self.study_detail)}{condition}；'
            f'研究中观察到：{escape(self.finding_detail)}。 '
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
            "有经验组冥想时，较快、常跟呼吸一起变化的心率起伏增强，"
            "较慢起伏所占的比重下降，并观察到更规则的心率起伏"
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
            "放松反应与分段呼吸时，出现约每10–20秒一次的较强心率起伏，"
            "心率与呼吸也更同步；火呼吸时平均心率升高，同步程度下降"
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
            "训练前冥想时，较快、常跟呼吸一起变化的心率起伏增强；"
            "训练后这类起伏仍增强，同时一部分约每10–17秒一次的较慢起伏减弱"
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
            "10名男性Vipassana经验者（20–61岁，至少2年练习，平均7.5年、每周约15小时）完成30分钟结构化冥想；因信号干扰排除3人："
            "Anapana 10分钟、Vipassana 15分钟、Metta 5分钟"
        ),
        finding_detail=(
            "前10分钟整体心率起伏减弱，中间15分钟较慢和较快的起伏一起增强，"
            "最后5分钟再次回落；中间阶段的节律变化最明显"
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
            "Theravada Vipassana时，较快、常跟呼吸一起变化的起伏增强，"
            "较慢与较快起伏的相对比例下降；Vajrayana的两种练习则出现较快起伏减弱"
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
            "研究同时比较不同快慢的心率起伏和它们随时间的变化，"
            "观察到呼吸带来的心率起伏会随练习经验不同而变化"
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
            "任务结束后，较快、常跟呼吸一起变化的起伏和快慢起伏比例很快回到休息水平，"
            "最慢的背景变化恢复得更慢"
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
            "研究在课程前后及一个月后重复观察心率与心跳起伏，"
            "用来比较短期课程前后与长期练习者的变化轨迹"
        ),
    ),
    LiteratureSource(
        source_id=9,
        authors=(
            "Sylvain Laborde, Mark S Allen, Uwe Borges, Fabien Dosseville, "
            "Thomas J Hosang, Martin Iskra, Emma Mosley, Chiara Salvotti, "
            "Luca Spolverato, Nicholas Zammit, Fabien Javelle"
        ),
        title=(
            "Effects of voluntary slow breathing on heart rate and heart rate variability: "
            "A systematic review and a meta-analysis"
        ),
        year=2022,
        journal="Neuroscience & Biobehavioral Reviews",
        url="https://pubmed.ncbi.nlm.nih.gov/35623448/",
        study_detail=(
            "系统综述与荟萃分析纳入223项自主慢呼吸研究，其中172项观察练习当下、16项观察单次练习后、49项观察多次训练后"
        ),
        finding_detail=(
            "慢呼吸期间、单次练习后以及多次训练后，反映心跳间隔起伏的多项指标总体都出现增强"
        ),
        condition_detail="自主放慢呼吸速度，包括腹式呼吸、膈肌呼吸和心率变异性反馈等做法",
        evidence_level="systematic_review_meta_analysis",
        transfer_note="适合支持缓慢而规律、整体起伏增强等形态；不能单独推出用户正在放松或冥想",
    ),
    LiteratureSource(
        source_id=10,
        authors=(
            "Hans Kirschner, Willem Kuyken, Kim Wright, Henrietta Roberts, "
            "Claire Brejcha, Anke Karl"
        ),
        title=(
            "Soothing Your Heart and Feeling Connected: A New Experimental Paradigm "
            "to Study the Benefits of Self-Compassion"
        ),
        year=2019,
        journal="Clinical Psychological Science",
        url="https://pubmed.ncbi.nlm.nih.gov/32655984/",
        study_detail=(
            "135名参与者随机进入两种短时自我关怀练习，以及反刍、中性和积极兴奋三种对照条件"
        ),
        finding_detail=(
            "两种自我关怀练习都出现心率下降、皮肤电活动下降和心跳间隔起伏增强的组合，反刍条件呈相反方向"
        ),
        condition_detail="短时自我关怀练习与三类对照条件比较",
        evidence_level="randomized_experiment",
        transfer_note="只支持安抚型身体组合的研究类比，不用于判断安全感、焦虑或其他心理状态",
    ),
    LiteratureSource(
        source_id=11,
        authors="Hye-Geum Kim, Eun-Jin Cheon, Dai-Seg Bai, Young Hwan Lee, Bon-Hoon Koo",
        title="Stress and Heart Rate Variability: A Meta-Analysis and Review of the Literature",
        year=2018,
        journal="Psychiatry Investigation",
        url="https://pubmed.ncbi.nlm.nih.gov/29486547/",
        study_detail=(
            "综述筛选出37篇使用心跳间隔变化观察人类心理压力反应的研究"
        ),
        finding_detail=(
            "多数研究在压力任务中观察到心跳间隔起伏发生变化，但不同任务和指标的方向并不完全一致"
        ),
        condition_detail="实验室心理压力与任务反应研究的综合整理",
        evidence_level="systematic_review",
        transfer_note="只用于支持投入或起伏收窄等形态可在压力任务中出现，不能据此诊断压力",
    ),
    LiteratureSource(
        source_id=12,
        authors="E S Mezzacappa, R M Kelsey, E S Katkin, R P Sloan",
        title="Vagal rebound and recovery from psychological stress",
        year=2001,
        journal="Psychosomatic Medicine",
        url="https://pubmed.ncbi.nlm.nih.gov/11485119/",
        study_detail=(
            "两组实验让参与者完成冷刺激、心算或Stroop等任务，并比较任务前、任务中和任务后的心率与心跳间隔变化"
        ),
        finding_detail=(
            "任务结束后的恢复阶段，心率可低于基线，而心跳间隔起伏可高于基线；最明显的回弹常出现在恢复开始阶段"
        ),
        condition_detail="急性任务结束后的短时恢复",
        evidence_level="controlled_experiment",
        transfer_note="支持从紧绷样变化向恢复样变化过渡的时间结构，不代表用户经历了同样的压力任务",
    ),
    LiteratureSource(
        source_id=13,
        authors="Antonio Luque-Casado, José C Perales, David Cárdenas, Daniel Sanabria",
        title="Heart rate variability and cognitive processing: The autonomic response to task demands",
        year=2016,
        journal="Biological Psychology",
        url="https://pubmed.ncbi.nlm.nih.gov/26638762/",
        study_detail=(
            "参与者完成持续注意、工作记忆和时长判断任务，并与控制条件比较，同时报告主观任务负荷"
        ),
        finding_detail=(
            "心跳间隔起伏会随任务要求改变，工作记忆任务中的整体起伏最低，并且随着持续做任务而进一步减小"
        ),
        condition_detail="持续注意与认知任务",
        evidence_level="controlled_experiment",
        transfer_note="适合支持进入专注或整体起伏收窄的研究类比，不等同于用户主观专注程度",
    ),
    LiteratureSource(
        source_id=14,
        authors="Amy R Borchardt, Peggy M Zoccola",
        title="Recovery from stress: an experimental examination of focused attention meditation in novices",
        year=2018,
        journal="Journal of Behavioral Medicine",
        url="https://pubmed.ncbi.nlm.nih.gov/29850971/",
        study_detail=(
            "99名没有冥想经验的大学生在标准化压力任务后，被随机分配到专注冥想、听有声书或安静坐着三种恢复条件"
        ),
        finding_detail=(
            "三组的心跳间隔起伏在恢复期都回到基线；冥想组还出现了皮肤电恢复，以及更完整的情绪自评回归"
        ),
        condition_detail="压力任务后的恢复与短时专注练习",
        evidence_level="randomized_experiment",
        transfer_note="支持恢复过程可能有多种路径；不能把某种恢复形态直接解释成正在冥想",
    ),
    LiteratureSource(
        source_id=15,
        authors="Valerie L Jentsch, Oliver T Wolf",
        title=(
            "The impact of emotion regulation on cardiovascular, neuroendocrine "
            "and psychological stress responses"
        ),
        year=2020,
        journal="Biological Psychology",
        url="https://pubmed.ncbi.nlm.nih.gov/32437903/",
        study_detail=(
            "86名女性在压力任务中分别采用重新评价、表达抑制或对照策略"
        ),
        finding_detail=(
            "重新评价组在任务中一度出现更小的心跳间隔起伏，但任务结束后的回升比表达抑制组更强"
        ),
        condition_detail="压力任务中的情绪调节策略及任务后恢复",
        evidence_level="controlled_experiment",
        transfer_note="支持先收窄、随后回弹的时序结构；不能由腕带数据推断用户采用了某种情绪调节策略",
    ),
    LiteratureSource(
        source_id=16,
        authors=(
            "Lydia Brown, Alora A Rando, Kristina Eichel, Nicholas T Van Dam, "
            "Christopher M Celano, Jeff C Huffman, Meg E Morris"
        ),
        title=(
            "The Effects of Mindfulness and Meditation on Vagally Mediated Heart Rate Variability: "
            "A Meta-Analysis"
        ),
        year=2021,
        journal="Psychosomatic Medicine",
        url="https://pubmed.ncbi.nlm.nih.gov/33395216/",
        study_detail=(
            "荟萃分析纳入19项以静坐为主的正念或冥想随机对照试验，比较训练后静息状态的心跳间隔变化"
        ),
        finding_detail=(
            "总体结果没有显示训练相对对照能稳定提高静息时的心跳间隔起伏，而且不同研究之间差异很大"
        ),
        condition_detail="正念与冥想随机对照研究的综合结果",
        evidence_level="meta_analysis_caution",
        transfer_note="作为解释边界：相似节律只能表示形态相似，不能把更大的起伏直接等同于冥想效果",
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
