import xml.etree.ElementTree as ET
import utils
from os.path import basename, isfile, join
from os import listdir, remove
import json
import joblib as jl
from sklearn import tree
from sklearn.ensemble import RandomForestClassifier
from sklearn.gaussian_process import GaussianProcessClassifier
from sklearn import svm
from sklearn.decomposition import PCA
import graphviz
import numpy
import logging


class EDIRDoc(object):
    """
    a class for reading EDIR annotation doc (XML)
    """
    def __init__(self, file_path):
        self._path = file_path
        self._root = None
        self._full_text = None
        self._word_offset_start = -1
        self._entities = None
        self.load()

    @property
    def file_path(self):
        return self._path

    def load(self):
        if not isfile(self.file_path):
            logging.debug('%s is NOT a file' % self.file_path)
            return
        tree = ET.parse(self.file_path)
        self._root = tree.getroot()
        self.get_word_offset_start()

    @property
    def get_full_text(self):
        if self._full_text is not None:
            return self._full_text
        if self._root is None:
            self.load()
        root = self._root
        d = ''
        start_offset = -1
        for p in root.findall('.//p'):
            for s in p:
                if 'proc' in s.attrib: # and s.attrib['proc'] == 'yes':
                    for w in s:
                        id_val = int(w.attrib['id'][1:])
                        if start_offset == -1:
                            start_offset = id_val
                        offset = id_val - start_offset
                        d += ' ' * (offset - len(d)) + w.text
        self._full_text = d
        return d

    def get_word_offset_start(self):
        if self._word_offset_start >= 0:
            return self._word_offset_start
        root = self._root
        offset_start = -1
        for e in root.findall('.//p/s[@proc]/w'):
            if 'id' not in e.attrib:
                continue
            else:
                offset_start = int(e.attrib['id'][1:])
                break
        if offset_start == -1:
            logging.debug('%s offset start could not be found' % self.file_path)
        self._word_offset_start = offset_start

    def get_ess_entities(self):
        if self._entities is not None:
            return self._entities
        root = self._root
        offset_start = self.get_word_offset_start()
        entities = []
        for e in root.findall('.//standoff/ents/ent'):
            if 'type' not in e.attrib:
                continue
            ent_type = e.attrib['type']
            if ent_type.startswith('label:'):
                continue
            negated = False
            if 'neg_' in ent_type:
                negated = True
                ent_type = ent_type.replace(r'neg_', '')
            str = ' '.join([part.text for part in e.findall('./parts/part')])
            ent_start = -1
            ent_end = -1
            for part in e.findall('./parts/part'):
                ent_start = int(part.attrib['sw'][1:]) - offset_start
                ent_end = ent_start + len(part.text)
            ann = EDIRAnn(str=str, start=ent_start, end=ent_end, type=ent_type)
            ann.negated = negated
            ann.id = len(entities)
            entities.append(ann)
        self._entities = entities
        return self._entities


class BasicAnn(object):
    """
    a simple NLP (Named Entity) annotation class
    """
    def __init__(self, str, start, end):
        self._str = str
        self._start = start
        self._end = end
        self._id = -1

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, value):
        self._id = value

    @property
    def str(self):
        return self._str

    @str.setter
    def str(self, value):
        self._str = value

    @property
    def start(self):
        return self._start

    @start.setter
    def start(self, value):
        self._start = value

    @property
    def end(self):
        return self._end

    @end.setter
    def end(self, value):
        self._end = value

    def overlap(self, other_ann):
        if other_ann.start <= self.start <= other_ann.end or other_ann.start <= self.end <= other_ann.end:
            return True
        else:
            return False

    def is_larger(self, other_ann):
        return self.start <= other_ann.start and self.end >= other_ann.end \
               and not (self.start == other_ann.start and self.end == other_ann.end)


class EDIRAnn(BasicAnn):
    """
    EDIR annotation class
    """
    def __init__(self, str, start, end, type):
        self._type = type
        super(EDIRAnn, self).__init__(str, start, end)
        self._negated = False

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, value):
        self._type = value

    @property
    def negated(self):
        return self._negated

    @negated.setter
    def negated(self, value):
        self._negated = value

    @property
    def label(self):
        t = self.type
        if self.negated:
            t = 'neg_' + t
        return t


class ContextedAnn(BasicAnn):
    """
    a contextulised annotation class (negation/tempolarity/experiencer)
    """
    def __init__(self, str, start, end, negation, temporality, experiencer):
        self._neg = negation
        self._temp = temporality
        self._exp = experiencer
        super(ContextedAnn, self).__init__(str, start, end)

    @property
    def negation(self):
        return self._neg

    @negation.setter
    def negation(self, value):
        self._neg = value

    @property
    def temporality(self):
        return self._temp

    @temporality.setter
    def temporality(self, value):
        self._temp = value

    @property
    def experiencer(self):
        return self._exp

    @experiencer.setter
    def experiencer(self, value):
        self._exp = value


class PhenotypeAnn(ContextedAnn):
    """
    a simple customisable phenotype annotation (two attributes for customised attributes)
    """
    def __init__(self, str, start, end,
                 negation, temporality, experiencer,
                 major_type, minor_type):
        super(PhenotypeAnn, self).__init__(str, start, end, negation, temporality, experiencer)
        self._major_type = major_type
        self._minor_type = minor_type

    @property
    def major_type(self):
        return self._major_type

    @major_type.setter
    def major_type(self, value):
        self._major_type = value

    @property
    def minor_type(self):
        return self._minor_type

    @minor_type.setter
    def minor_type(self, value):
        self._minor_type = value


class SemEHRAnn(ContextedAnn):
    """
    SemEHR Annotation Class
    """
    def __init__(self, str, start, end,
                 negation, temporality, experiencer,
                 cui, sty, pref, ann_type):
        super(SemEHRAnn, self).__init__(str, start, end, negation, temporality, experiencer)
        self._cui = cui
        self._sty = sty
        self._pref = pref
        self._ann_type = ann_type

    @property
    def cui(self):
        return self._cui

    @cui.setter
    def cui(self, value):
        self._cui = value

    @property
    def sty(self):
        return self._sty

    @sty.setter
    def sty(self, value):
        self._sty = value

    @property
    def ann_type(self):
        return self._ann_type

    @ann_type.setter
    def ann_type(self, value):
        self._ann_type = value

    @property
    def pref(self):
        return self._pref

    @pref.setter
    def pref(self, value):
        self._pref = value


class SemEHRAnnDoc(object):
    """
    SemEHR annotation Doc
    """
    def __init__(self, file_path):
        self._doc = utils.load_json_data(file_path)
        self._anns = []
        self._phenotype_anns = []
        self._sentences = []
        self._others = []
        self.load_anns()

    def load_anns(self):
        all_anns = self._anns
        panns = self._phenotype_anns
        for anns in self._doc['annotations']:
            for ann in anns:
                t = ann['type']
                if t == 'Mention':
                    a = SemEHRAnn(ann['features']['string_orig'],
                                  int(ann['startNode']['offset']),
                                  int(ann['endNode']['offset']),

                                  ann['features']['Negation'],
                                  ann['features']['Temporality'],
                                  ann['features']['Experiencer'],

                                  ann['features']['inst'],
                                  ann['features']['STY'],
                                  ann['features']['PREF'],
                                  t)
                    all_anns.append(a)
                    a.id = 'cui-%s' % len(all_anns)
                elif t == 'Phenotype':
                    a = PhenotypeAnn(ann['features']['string_orig'],
                                      int(ann['startNode']['offset']),
                                      int(ann['endNode']['offset']),

                                      ann['features']['Negation'],
                                      ann['features']['Temporality'],
                                      ann['features']['Experiencer'],

                                      ann['features']['majorType'],
                                      ann['features']['minorType'])
                    panns.append(a)
                    a.id = 'phe-%s' % len(panns)
                elif t == 'Sentence':
                    a = BasicAnn('Sentence',
                                 int(ann['startNode']['offset']),
                                 int(ann['endNode']['offset']))
                    self._sentences.append(a)
                    a.id = 'sent-%s' % len(self._sentences)
                else:
                    self._others.append(ann)

        sorted(all_anns, key=lambda x: x.start)

    @property
    def annotations(self):
        return self._anns

    @property
    def sentences(self):
        return self._sentences

    @property
    def phenotypes(self):
        return self._phenotype_anns

    def learn_mappings_from_labelled(self, labelled_doc, lbl2insts, lbl2missed):
        ed = labelled_doc
        sd = self
        for e in ed.get_ess_entities():
            matched = False
            for a in sd.annotations:
                if a.overlap(e) and not e.is_larger(a):
                    matched = True
                    if e.type not in lbl2insts:
                        lbl2insts[e.type] = set()
                    lbl2insts[e.type].add('\t'.join([a.cui, a.pref, a.sty]))
                    continue
            # if not matched:
            if True:
                if e.type not in lbl2missed:
                    lbl2missed[e.type] = []
                lbl2missed[e.type].append(e.str.lower())


class Concept2Mapping(object):
    """
    a mapping from annotations to phenotypes
    """
    def __init__(self, concept_map_file):
        self._concept_map_file = concept_map_file
        self._cui2label = {}
        self._concept2label = None
        self.load_concept_mappings()

    def load_concept_mappings(self):
        concept_mapping = utils.load_json_data(self._concept_map_file)
        concept2types = {}
        for t in concept_mapping:
            for text in concept_mapping[t]:
                c = text[:8] # only to get the CUI
                arr = text.split('\t')
                self._cui2label[c] = arr[1]
                if c not in concept2types:
                    concept2types[c] = []
                concept2types[c].append(t)
        self._concept2label = concept2types

    @property
    def cui2label(self):
        return self._cui2label

    @property
    def concept2label(self):
        return self._concept2label

    @concept2label.setter
    def concept2label(self, value):
        self._concept2label = value


class CustomisedRecoginiser(SemEHRAnnDoc):
    """
    recognise target labels based on identified UMLS entities and
    customised labels
    """
    def __init__(self, file_path, concept_mapping):
        super(CustomisedRecoginiser, self).__init__(file_path=file_path)
        self._concept_mapping = concept_mapping
        self._mapped = None
        self._phenotypes = None
        self._combined = None

    @property
    def concept2label(self):
        return self._concept_mapping.concept2label

    def get_mapped_labels(self):
        if self._mapped is not None:
            return self._mapped
        mapped = []
        for ann in self.annotations:
            if ann.cui in self.concept2label:
                for t in self.concept2label[ann.cui]:
                    ea = EDIRAnn(ann.str, ann.start, ann.end, t)
                    ea.negated = ann.negation == 'Negated'
                    ea.id = ann.id
                    mapped.append(ea)
        self._mapped = mapped
        return mapped

    def get_customised_phenotypes(self):
        if self._phenotypes is not None:
            return self._phenotypes
        self._phenotypes = []
        for ann in self.phenotypes:
            ea = EDIRAnn(ann.str, ann.start, ann.end, ann.minor_type)
            ea.negated = ann.negation == 'Negated'
            ea.id = ann.id
            self._phenotypes.append(ea)
        return self._phenotypes

    def get_ann_sentence(self, ann):
        sent = None
        for s in self.sentences:
            if ann.overlap(s):
                sent = s
                break
        if sent is None:
            print 'sentence not found for %s' % ann.__dict__
            return None
        return sent

    def get_previous_sentences(self, ann, include_self=True):
        sent = self.get_ann_sentence(ann)
        if sent is None:
            return None
        sents = []
        for s in self.sentences:
            if s.start < sent.start:
                sents.append(s)
        return sents + ([] if not include_self else [sent])

    def get_sent_anns(self, sent, ann_ignore=None):
        ret = {'umls': [], 'phenotype': []}
        for a in self.annotations:
            if a.overlap(sent):
                if ann_ignore is not None and ann_ignore.overlap(a):
                    continue
                ret['umls'].append(a)
        for a in self.phenotypes:
            if a.overlap(sent):
                if ann_ignore is not None and  ann_ignore.overlap(a):
                    continue
                ret['phenotype'].append(a)
        return ret

    def get_same_sentence_anns(self, ann):
        sent = self.get_ann_sentence(ann)
        if sent is None:
            return None
        return self.get_sent_anns(sent, ann)

    def get_prior_anns(self, ann):
        sents = self.get_previous_sentences(ann)
        ret = {'umls': [], 'phenotype': []}
        for s in sents[-1:]:
            r = self.get_sent_anns(s, ann_ignore=ann)
            ret['umls'] += r['umls']
            ret['phenotype'] += r['phenotype']
        return ret

    def get_anns_by_label(self, label, ignore_mappings=[]):
        anns = []
        t = label.replace('neg_', '')
        for a in self.annotations:
            if a.cui not in self.concept2label:
                continue
            if a.cui in ignore_mappings:
                continue
            if t in self.concept2label[a.cui]:
                if label.startswith('neg_') and a.negation == 'Negated':
                    anns.append(a)
                elif not label.startswith('neg_') and a.negation != 'Negated':
                    anns.append(a)
        phenotypes = []
        smaller_to_remove = []
        for a in self.phenotypes:
            if a.minor_type == t:
                if a.str.lower() in [s.lower() for s in ignore_mappings]:
                    continue
                if (label.startswith('neg_') and a.negation == 'Negated') or \
                        (not label.startswith('neg_') and a.negation != 'Negated'):
                    overlaped = False
                    for ann in anns + phenotypes:
                        if ann.overlap(a):
                            if a.is_larger(ann):
                                smaller_to_remove.append(ann)
                            else:
                                overlaped = True
                                break
                    if not overlaped:
                        phenotypes.append(a)
        for o in smaller_to_remove:
            if o in anns:
                anns.remove(o)
            if o in phenotypes:
                phenotypes.remove(o)
        return anns + phenotypes

    def get_combined_anns(self):
        if self._combined is not None:
            return self._combined
        anns = [] + self.get_mapped_labels()
        for ann in self.get_customised_phenotypes():
            overlaped = False
            for m in self.get_mapped_labels():
                if ann.overlap(m):
                    overlaped = True
                    break
            if not overlaped:
                anns.append(ann)
        self._combined = anns
        return anns

    def validate_mapped_performance(self, gold_anns, label2performance):
        CustomisedRecoginiser.validate(gold_anns, self.get_mapped_labels(), label2performance)

    def validate_combined_performance(self, gold_anns, label2performance):
        CustomisedRecoginiser.validate(gold_anns,
                                       self.get_combined_anns(),
                                       label2performance)

    @staticmethod
    def validate(gold_anns, learnt_anns, label2performance):
        matched_ann_ids = []
        for ga in gold_anns:
            l = ga.label
            if l not in label2performance:
                label2performance[l] = LabelPerformance(l)
            performance = label2performance[l]
            matched = False
            for la in learnt_anns:
                if la.label == l and la.overlap(ga):
                    matched = True
                    performance.increase_true_positive()
                    matched_ann_ids.append(la.id)
                    break
            if not matched:
                performance.increase_false_negative()
        for la in learnt_anns:
            if la.id not in matched_ann_ids:
                l = la.label
                if l not in label2performance:
                    label2performance[l] = LabelPerformance(l)
                performance = label2performance[l]
                performance.increase_false_positive()

    @staticmethod
    def print_performances(label2performances):
        s = ''.join(['*' * 10, 'performance', '*' * 10])
        s += '\n%s\t%s\t%s\t%s\t%s\t%s\n' % ('label', 'precision', 'recall', 'f1', '#insts', 'false positive')
        for t in label2performances:
            p = label2performances[t]
            s += '%s\t%s\t%s\t%s\t%s\t%s\n' % (t, p.precision, p.recall, p.f1, p.true_positive + p.false_negative,
                                           p.false_positive)
        logging.getLogger('performance').info(s)


class LabelModel(object):
    """
    a machine learning based class for inferring phenotypes from NLP results
    features:
    - feature weighing
    - transparent models
    """
    def __init__(self, label, max_dimensions=None):
        self._label = label
        self._context_dimensions = []
        self._label_dimensions = []
        self._cui2label = {}
        self._label2freq = {}
        self._selected_dims = None
        self._max_dimensions = 2000 if max_dimensions == None else max_dimensions
        self._tp_labels = set()
        self._fp_labels = set()
        self._tps = 0
        self._fps = 0
        self._tfidf_dims = None
        self._lbl_one_dimension = True

    @property
    def use_one_dimension_for_label(self):
        return self._lbl_one_dimension

    @use_one_dimension_for_label.setter
    def use_one_dimension_for_label(self, value):
        self._lbl_one_dimension = value

    @property
    def cui2label(self):
        return self._cui2label

    @property
    def label(self):
        return self._label

    def add_label_dimension(self, value, tp=None, fp=None):
        if value.lower() not in self._label_dimensions:
            self._label_dimensions.append(value.lower())
            if tp is not None:
                self._tp_labels.add(value.lower())
            if fp is not None:
                self._fp_labels.add(value.lower())

    def add_label_dimension_by_annotation(self, ann, tp=None, fp=None):
        self.add_label_dimension(LabelModel.get_ann_dim_label(ann), tp=tp, fp=fp)

    def add_context_dimension(self, value, tp=None, fp=None):
        if value.lower() not in self._context_dimensions:
            self._context_dimensions.append(value.lower())
            self._label2freq[value.lower()] = 1
        else:
            self._label2freq[value.lower()] = self._label2freq[value.lower()] + 1
        if tp is not None:
            self._tp_labels.add(value.lower())
        if fp is not None:
            self._fp_labels.add(value.lower())

    def add_context_dimension_by_annotation(self, ann, tp=None, fp=None):
        self.add_context_dimension(LabelModel.get_ann_dim_label(ann, generalise=True), tp=tp, fp=fp)

    def get_top_freq_dimensions(self, k):
        if self._selected_dims is not None:
            return self._selected_dims
        df = [(l, self._label2freq[l]) for l in self._label2freq]
        df = sorted(df, key=lambda x: -x[1])
        self._selected_dims = [d[0] for d in df[:k]]
        return self._selected_dims

    def get_top_tfidf_dimensions(self, k):
        if self._tfidf_dims is not None:
            return self._tfidf_dims
        idf_weight = 1.0
        if self._tps > 0 and self._fps > 0:
            idf_weight = 1.0 * self._tps / self._fps
        logging.debug(self._label2freq)
        df = []
        for l in self._label2freq:
            idf = 1.0 / ( (1 if l in self._tp_labels else 0) + (1 if l in self._fp_labels else 0) )
            score = self._label2freq[l]
            if idf_weight == 1 or (l in self._tp_labels and l in self._fp_labels):
                score = score * idf
                if l in self._tp_labels and l in self._fp_labels:
                    score = 0.0
            elif l in self._fp_labels:
                score *= idf_weight * idf
            df.append((l, score))
        df = sorted(df, key=lambda x: -x[1])
        logging.debug(df)
        self._tfidf_dims = [d[0] for d in df[:k]]
        return self._tfidf_dims

    @property
    def max_dimensions(self):
        return self._max_dimensions

    @max_dimensions.setter
    def max_dimensions(self, value):
        if value is None:
            self._max_dimensions = 2000
        self._max_dimensions = value

    @property
    def label_dimensions(self):
        return self._label_dimensions

    @property
    def context_dimensions(self):
        return self._context_dimensions

    def encode_ann(self, ann, context_anns):
        ann_label = LabelModel.get_ann_dim_label(ann)
        encoded = []
        if self.use_one_dimension_for_label:
            if ann_label in self.label_dimensions:
                encoded.append(self.label_dimensions.index(ann_label))
            else:
                encoded.append(-1)
        else:
            for lbl in self.label_dimensions:
                if lbl == ann_label:
                    encoded.append(1)
                else:
                    encoded.append(0)
        context_labels = [LabelModel.get_ann_dim_label(ann, generalise=True) for ann in context_anns]
        for l in self.get_top_tfidf_dimensions(self.max_dimensions): # self.context_dimensions:
            freq = 0
            # for cl in context_labels:
            #     if cl.lower() == l.lower():
            #         freq += 1
            if l in context_labels:
                encoded.append(1)
            else:
                encoded.append(0)
            encoded.append(freq)
        return encoded

    def collect_dimensions(self, ann_dir):
        cm = Concept2Mapping(_concept_mapping)
        file_keys = [f.split('.')[0] for f in listdir(ann_dir) if isfile(join(ann_dir, f))]
        # collect dimension labels
        for fk in file_keys:
            cr = CustomisedRecoginiser(join(ann_dir, '%s.json' % fk), cm)
            t = self.label.replace('neg_', '')
            anns = cr.get_anns_by_label(t)
            neg_anns = cr.get_anns_by_label('neg_' + t)
            for a in anns + neg_anns:
                self.add_label_dimension_by_annotation(a)
                # self.add_context_dimension_by_annotation(a)
                if (a.negation != 'Negated' and self.label.startswith('neg_')) or \
                        (a.negation == 'Negated' and not self.label.startswith('neg_')):
                    continue
                sanns = cr.get_same_sentence_anns(a)
                context_anns = [] + sanns['umls'] + sanns['phenotype']
                #collect cui labels
                for u in sanns['umls']:
                    self._cui2label[u.cui] = u.pref
                for c in context_anns:
                    self.add_context_dimension_by_annotation(c)

    def collect_tfidf_dimensions(self, ann_dir, gold_dir):
        cm = Concept2Mapping(_concept_mapping)
        file_keys = [f.split('.')[0] for f in listdir(ann_dir) if isfile(join(ann_dir, f))]
        # collect dimension labels
        tp_freq = 0
        fp_freq = 0
        for fk in file_keys:
            cr = CustomisedRecoginiser(join(ann_dir, '%s.json' % fk), cm)
            gd = EDIRDoc(join(gold_dir, '%s-ann.xml' % fk))
            if not isfile(join(gold_dir, '%s-ann.xml' % fk)):
                continue
            t = self.label.replace('neg_', '')
            anns = cr.get_anns_by_label(t)
            neg_anns = cr.get_anns_by_label('neg_' + t)

            not_matched_gds = []
            for e in gd.get_ess_entities():
                if e.label == self.label:
                    not_matched_gds.append(e.id)

            for a in anns + neg_anns:
                # self.add_context_dimension_by_annotation(a)
                self.add_label_dimension_by_annotation(a)
                if (a.negation != 'Negated' and self.label.startswith('neg_')) or \
                        (a.negation == 'Negated' and not self.label.startswith('neg_')):
                    continue

                matched = False
                for g in gd.get_ess_entities():
                    if g.id in not_matched_gds:
                        if g.overlap(a) and g.label == self.label:
                            matched = True
                            tp_freq += 1
                            not_matched_gds.remove(g.id)
                if not matched:
                    fp_freq += 1

                sanns = cr.get_prior_anns(a)
                context_anns = [] + sanns['umls'] + sanns['phenotype']
                #collect cui labels
                for u in sanns['umls']:
                    self._cui2label[u.cui] = u.pref
                for c in context_anns:
                    self.add_context_dimension_by_annotation(c, tp=True if matched else None,
                                                             fp=True if not matched else None)
        self._tps = tp_freq
        self._fps = fp_freq
        logging.debug('tp: %s, fp: %s' % (tp_freq, fp_freq))

    def load_data(self, ann_dir, gold_dir, verbose=True, ignore_mappings=[]):
        # print self.get_top_tfidf_dimensions(self.max_dimensions)
        cm = Concept2Mapping(_concept_mapping)
        file_keys = [f.split('.')[0] for f in listdir(ann_dir) if isfile(join(ann_dir, f))]
        X = []
        Y = []
        false_negatives = 0
        multiple_true_positives = 0
        for fk in file_keys:
            cr = CustomisedRecoginiser(join(ann_dir, '%s.json' % fk), cm)
            if not isfile(join(gold_dir, '%s-ann.xml' % fk)):
                continue
            gd = EDIRDoc(join(gold_dir, '%s-ann.xml' % fk))

            not_matched_gds = []
            for e in gd.get_ess_entities():
                if e.label == self.label:
                    not_matched_gds.append(e.id)

            anns = cr.get_anns_by_label(self.label, ignore_mappings=ignore_mappings)
            for a in anns:
                t2anns = cr.get_prior_anns(a)
                context_anns = [] + t2anns['umls'] + t2anns['phenotype']
                matched = False
                for g in gd.get_ess_entities():
                    if g.id in not_matched_gds:
                        if g.overlap(a) and g.label == self.label:
                            if matched:
                                multiple_true_positives += 1
                            matched = True
                            not_matched_gds.remove(g.id)
                if verbose:
                    if not matched:
                        logging.debug('%s %s %s' % ('!',
                                      self.get_ann_dim_label(a) +
                                      ' // ' + ' | '.join(self.get_ann_dim_label(a, generalise=True)
                                                          for a in context_anns), fk))
                    else:
                        logging.debug('%s %s %s' % ('R',
                                      a.str + ' // ' + ' | '.join(self.get_ann_dim_label(a, generalise=True)
                                                                  for a in context_anns), fk))
                Y.append([1 if matched else 0])
                X.append(self.encode_ann(a, context_anns))
            false_negatives += len(not_matched_gds)

            missed = None
            for g in gd.get_ess_entities():
                if g.id in not_matched_gds:
                    missed = g
                    logging.debug('\t'.join(['M',  g.str, str(g.negated), str(g.start), str(g.end), join(gold_dir, '%s-ann.xml' % fk)]))
            # if len(not_matched_gds) > 0:
            #     print not_matched_gds
            #     for a in anns:
            #         logging.debug(a.str, a.start, a.end, missed.overlap(a))
        return {'X': X, 'Y': Y, 'fns': false_negatives, 'mtp': multiple_true_positives}

    def serialise(self, output_file):
        jl.dump(self, output_file)

    @staticmethod
    def deserialise(serialised_file):
        return jl.load(serialised_file)

    @staticmethod
    def get_ann_dim_label(ann, generalise=False):
        negated = ''
        label = ann.str
        if (hasattr(ann, 'negation') and ann.negation == 'Negated') or (hasattr(ann, 'negated') and ann.negated):
            negated = 'neg_'
        # if hasattr(ann, 'cui'):
        #     label = ann.cui
        # if generalise and hasattr(ann, 'sty'):
        #     label = ann.sty
            # if ann.sty.lower() == 'body part, organ, or organ component':
        return negated + label.lower()
        # return ann.str.lower() if not isinstance(ann, SemEHRAnn) else ann.cui.lower()

    @staticmethod
    def decision_tree_learning(X, Y, lm, output_file=None, pca_dim=None, pca_file=None, tree_viz_file=None):
        if len(X) <= _min_sample_size:
            logging.warning('not enough data found for prediction: %s' % lm.label)
            if isfile(output_file):
                remove(output_file)
            return
        pca = None
        if pca_dim is not None:
            pca = PCA(n_components=pca_dim)
            X_new = pca.fit_transform(X)
        else:
            X_new = X
        clf = tree.DecisionTreeClassifier()
        clf = clf.fit(X_new, Y)
        if output_file is not None:
            jl.dump(clf, output_file)
            logging.info('model file saved to %s' % output_file)
        if pca is not None and pca_file is not None:
            jl.dump(pca, pca_file)
        if tree_viz_file is not None:
            label_feature_names = []
            if lm.use_one_dimension_for_label:
                label_feature_names.append('label')
            else:
                for l in lm.label_dimensions:
                    if l.upper() in lm.cui2label:
                        label_feature_names.append('lbl: ' + lm.cui2label[l.upper()])
                    else:
                        label_feature_names.append('lbl: ' + l.upper())
            dot_data = tree.export_graphviz(clf, out_file=None,
                                            filled=True, rounded=True,
                                            feature_names=label_feature_names +
                                                          [(str(lm.cui2label[l.upper()]) + '(' + l.upper() + ')') if l.upper() in lm.cui2label else l
                                                           for l in lm.context_dimensions],
                                            class_names=['Yes', 'No'],
                                            special_characters=True)
            graph = graphviz.Source(dot_data)
            graph.render(tree_viz_file)

    @staticmethod
    def random_forest_learning(X, Y, output_file=None):
        if len(X) == 0:
            logging.warning('no data found for prediction')
            return
        clf = RandomForestClassifier()
        clf = clf.fit(X, Y)
        if output_file is not None:
            jl.dump(clf, output_file)
            logging.info('model file saved to %s' % output_file)

    @staticmethod
    def svm_learning(X, Y, output_file=None):
        if len(X) == 0:
            logging.info('no data found for prediction')
            return
        v = -1
        all_same = True
        for y in Y:
            if v == -1:
                v = y[0]
            if v != y[0]:
                all_same = False
                break
        if all_same:
            logging.warning('all same labels %s' % Y)
            return
        clf = svm.NuSVC()
        clf = clf.fit(X, Y)
        if output_file is not None:
            jl.dump(clf, output_file)
            logging.info('model file saved to %s' % output_file)

    @staticmethod
    def gpc_learning(X, Y, output_file=None):
        gpc = GaussianProcessClassifier().fit(X, Y)
        if output_file is not None:
            jl.dump(gpc, output_file)
            logging.info('model file saved to %s' % output_file)

    @staticmethod
    def predict_use_model(X, Y, fns, multiple_tps, model_file, performance,
                          pca_model_file=None):
        all_true = False
        if not isfile(model_file):
            logging.info('model file NOT FOUND: %s' % model_file)
            all_true = True
        else:
            if pca_model_file is not None:
                pca = jl.load(pca_model_file)
                X_new = pca.transform(X)
            else:
                X_new = X
            m = jl.load(model_file)
            P = m.predict(X_new)
            if fns > 0:
                logging.debug('missed instances: %s' % fns)
                performance.increase_false_negative(fns)
            if multiple_tps > 0:
                performance.increase_true_positive(multiple_tps)
        if all_true or len(X) <= _min_sample_size:
            logging.warn('using querying instead of predicting')
            P = numpy.ones(len(X))
        else:
            logging.info('instance size %s' % len(P))
        for idx in xrange(len(P)):
            if P[idx] == Y[idx]:
                if P[idx] == 1.0:
                    performance.increase_true_positive()
            elif P[idx] == 1.0:
                performance.increase_false_positive()
            else:
                performance.increase_false_negative()


class LabelPerformance(object):
    """
    precision/recall/f1 calculation on TP/FN/FP values
    """
    def __init__(self, label):
        self._label = label
        self._tp = 0
        self._fn = 0
        self._fp = 0

    def increase_true_positive(self, k=1):
        self._tp += k

    def increase_false_negative(self, k=1):
        self._fn += k

    def increase_false_positive(self, k=1):
        self._fp += k

    @property
    def true_positive(self):
        return self._tp

    @property
    def false_negative(self):
        return self._fn

    @property
    def false_positive(self):
        return self._fp

    @property
    def precision(self):
        if self._tp + self._fp == 0:
            return -1
        else:
            return 1.0 * self._tp / (self._tp + self._fp)

    @property
    def recall(self):
        if self._tp + self._fn == 0:
            return -1
        else:
            return 1.0 * self._tp / (self._tp + self._fn)

    @property
    def f1(self):
        if self.precision == -1 or self.recall == -1 or self.precision == 0 or self.recall == 0:
            return -1
        else:
            return 2 / (1/self.precision + 1/self.recall)


class StrokeSettings(object):
    """
    json based configuration setting
    """
    def __init__(self, setting_file):
        self._file = setting_file
        self._setting = {}
        self.load()

    def load(self):
        self._setting = utils.load_json_data(self._file)

    @property
    def settings(self):
        return self._setting



def extract_doc_level_ann(ann_dump, output_folder):
    """

    extract doc level annotations and save to separate files
    :param ann_dump:
    :param output_folder:
    :return:
    """
    lines = utils.read_text_file(ann_dump)
    for l in lines:
        doc_ann = json.loads(l)
        utils.save_string(l, join(output_folder, doc_ann['docId'].split('.')[0] + '.json'))


def extract_all_doc_anns(dump_folder, output_folder):
    dumps = [f for f in listdir(dump_folder) if isfile(join(dump_folder, f))]
    for d in dumps:
        extract_doc_level_ann(join(dump_folder, d), output_folder)


def save_full_text(xml_file, output_dir):
    """
    recover full text from Informatics' xml format
    :param xml_file:
    :param output_dir:
    :return:
    """
    if not isfile(xml_file):
        return
    ed = EDIRDoc(xml_file)
    fn = basename(xml_file)
    name = fn.replace(r'-ann.xml', '.txt')
    logging.info('%s processed to be %s' % (fn, name))
    utils.save_string(ed.get_full_text, join(output_dir, name))


def process_files(read_dir, write_dir):
    utils.multi_thread_process_files(read_dir, file_extension='xml', num_threads=10,
                                     process_func=save_full_text, args=[write_dir])


def get_doc_level_inference(label_dir, ann_dir, file_key, type2insts, type2inst_2, t2missed):
    """
    learn concept to label inference from gold standard - i.e. querying SemEHR annotations to
    draw conclusions
    :param label_dir:
    :param ann_dir:
    :param file_key:
    :param type2insts:
    :param type2inst_2:
    :return:
    """
    label_file = '%s-ann.xml' % file_key
    ann_file = '%s.json' % file_key
    print join(label_dir, label_file)
    ed = EDIRDoc(join(label_dir, label_file))
    if not isfile(join(label_dir, label_file)):
        print 'not a file: %s' % join(label_dir, label_file)
        return
    sd = SemEHRAnnDoc(join(ann_dir, ann_file))
    sd.learn_mappings_from_labelled(ed, type2insts, t2missed)


def learn_concept_mappings(output_lst_folder):
    type2insts = {}
    type2insts_2 = {}
    label_dir = _gold_dir
    ann_dir = _ann_dir
    file_keys = [f.split('.')[0] for f in listdir(ann_dir) if isfile(join(ann_dir, f))]
    t2missed = {}
    for fk in file_keys:
        get_doc_level_inference(label_dir,
                                ann_dir,
                                fk,
                                type2insts,
                                type2insts_2,
                                t2missed)
    for t in type2insts:
        type2insts[t] = list(type2insts[t])
    print json.dumps(type2insts)
    print '\n' * 2
    for t in type2insts_2:
        type2insts_2[t] = list(type2insts_2[t])
    print json.dumps(type2insts_2)

    print '\n' * 2
    labels = []
    defs = []
    for t in t2missed:
        t2missed[t] = list(set(t2missed[t]))
        utils.save_string('\n'.join(t2missed[t]) + '\n', join(output_lst_folder, t + '.lst'))
        labels += [l.lower() for l in t2missed[t]]
        defs.append(t + '.lst' + ':StrokeStudy:' + t)
    print '\n' * 2
    print '\n'.join(defs)
    print json.dumps(t2missed)


def learn_prediction_model(label, ann_dir=None, gold_dir=None, model_file=None, model_dir=None,
                           ml_model_file=None,
                           pca_dim=None,
                           pca_model_file=None,
                           max_dimension=None,
                           ignore_mappings=[],
                           viz_file=None):
    model_changed = False
    if model_file is not None:
        lm = LabelModel.deserialise(model_file)
    else:
        model_changed = True
        lm = LabelModel(label)
        lm.collect_tfidf_dimensions(ann_dir=ann_dir, gold_dir=gold_dir)
    lm.use_one_dimension_for_label = False
    lm.max_dimensions = max_dimension
    if ann_dir is not None:
        data = lm.load_data(ann_dir, gold_dir, ignore_mappings=ignore_mappings)
        # lm.random_forest_learning(data['X'], data['Y'], output_file=ml_model_file)
        # lm.svm_learning(data['X'], data['Y'], output_file=ml_model_file)
        lm.decision_tree_learning(data['X'], data['Y'], lm,
                                  output_file=ml_model_file,
                                  pca_dim=pca_dim,
                                  pca_file=pca_model_file,
                                  tree_viz_file=viz_file)

    if model_dir is not None and model_changed:
        lm.serialise(join(model_dir, '%s.lm' % label))
        logging.debug('%s.lm saved' % label)


def predict_label(model_file, test_ann_dir, test_gold_dir, ml_model_file, performance,
                  pca_model_file=None,
                  max_dimension=None,
                  ignore_mappings=[]):
    lm = LabelModel.deserialise(model_file)
    lm.max_dimensions = max_dimension
    data = lm.load_data(test_ann_dir, test_gold_dir, ignore_mappings=ignore_mappings)
    if len(data['X']) > 0:
        logging.debug('dimensions %s' % len(data['X'][0]))
    lm.predict_use_model(data['X'], data['Y'], data['fns'], data['mtp'], ml_model_file, performance,
                         pca_model_file=pca_model_file)


def populate_semehr_results(label_dir, ann_dir, file_key,
                            label2performances, using_combined=False):
    label_file = '%s-ann.xml' % file_key
    ann_file = '%s.json' % file_key
    print join(label_dir, label_file)
    if not isfile(join(label_dir, label_file)):
        return

    ed = EDIRDoc(join(label_dir, label_file))
    cm = Concept2Mapping(_concept_mapping)
    cr = CustomisedRecoginiser(join(ann_dir, ann_file), cm)
    if using_combined:
        cr.validate_combined_performance(ed.get_ess_entities(), label2performances)
    else:
        cr.validate_mapped_performance(ed.get_ess_entities(), label2performances)


def populate_validation_results():
    label_dir = _gold_dir
    ann_dir = _ann_dir

    label2performances = {}
    file_keys = [f.split('.')[0] for f in listdir(ann_dir) if isfile(join(ann_dir, f))]
    for fk in file_keys:
        populate_semehr_results(label_dir, ann_dir, fk, label2performances, using_combined=False)
    CustomisedRecoginiser.print_performances(label2performances)


def do_learn_exp(viz_file, num_dimensions=[20]):
    results = {}
    for lbl in _labels:
        logging.info('working on [%s]' % lbl)
        _learning_model_file = _learning_model_dir + '/%s.lm' % lbl
        _ml_model_file = _learning_model_dir + '/%s_DT.model' % lbl
        _pca_model_file = None # '/afs/inf.ed.ac.uk/group/project/biomedTM/users/hwu/learning_models/%s_pca.model' % lbl
        pca_dim = None
        max_dimensions = num_dimensions

        t = lbl.replace('neg_', '')
        ignore_mappings = _ignore_mappings[t] if t in _ignore_mappings else []

        for dim in max_dimensions:
            logging.info('dimension setting: %s' % dim)
            learn_prediction_model(lbl,
                                   ann_dir=_ann_dir,
                                   gold_dir=_gold_dir,
                                   ml_model_file=_ml_model_file,
                                   model_dir=_learning_model_dir,
                                   pca_dim=pca_dim,
                                   pca_model_file=_pca_model_file,
                                   max_dimension=dim,
                                   ignore_mappings=ignore_mappings,
                                   viz_file=viz_file)
            pl = '%s dim[%s]' % (lbl, dim)
            performance = LabelPerformance(pl)
            results[pl] = performance
            predict_label(_learning_model_file,
                          _test_ann_dir,
                          _test_gold_dir,
                          _ml_model_file,
                          performance,
                          pca_model_file=_pca_model_file,
                          max_dimension=dim,
                          ignore_mappings=ignore_mappings)
        CustomisedRecoginiser.print_performances(results)


def save_text_files(settings):
    process_files(settings['test_gold_dir'],
                  settings['test_fulltext_dir'])


def extact_doc_anns():
    extract_all_doc_anns(settings['test_semehr_output_dir'],
                         settings['test_ann_dir'])


if __name__ == "__main__":
    logging.basicConfig(level='INFO', format='%(name)s %(asctime)s %(message)s')
    ss = StrokeSettings('./settings/ess_annotator1.json')
    settings = ss.settings
    _min_sample_size = settings['min_sample_size']
    _ann_dir = settings['ann_dir']
    _gold_dir = settings['gold_dir']
    _test_ann_dir = settings['test_ann_dir']
    _test_gold_dir = settings['test_gold_dir']
    _concept_mapping = settings['concept_mapping_file']
    _learning_model_dir = settings['learning_model_dir']
    _labels = utils.read_text_file(settings['entity_types_file'])
    _ignore_mappings = utils.load_json_data(settings['ignore_mapping_file'])

    # 1. extract text files for annotation
    # save_text_files(settings)
    # 2. run SemEHR on the text files
    # 3. extract doc anns into separate files from dumped JSON files
    # extact_doc_anns()
    # 4. learn umls concept to phenotype mappping
    # learn_concept_mappings(settings['gazetteer_dir'])
    # 5. learn phenotype inference
    do_learn_exp(settings['viz_file'])