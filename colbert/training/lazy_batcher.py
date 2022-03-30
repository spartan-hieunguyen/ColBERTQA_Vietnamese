import os
import ujson
import random

from underthesea import sent_tokenize

# import sys
# sys.path.insert(1, "../")
# from argparse import ArgumentParser
# parser = ArgumentParser()
# parser.add_argument('--query_maxlen', dest='query_maxlen', default=500, type=int)
# parser.add_argument('--doc_maxlen', dest='doc_maxlen', default=800, type=int)
# parser.add_argument('--pretrained_tokenizer', dest='pretrained_tokenizer', default="../pretrained/pretrained/bartpho")
# parser.add_argument('--bsize', dest='bsize', default=32, type=int)
# parser.add_argument('--positives', dest='positives', default="../dataset/document/positive_pairs.tsv")
# parser.add_argument('--queries', dest='queries', default="../dataset/document/queries.tsv")
# parser.add_argument('--collection', dest='collection', default="../dataset/document/collection.tsv")
# parser.add_argument('--accum', dest='accumsteps', default=2, type=int)
# args = parser.parse_args()


from functools import partial
from colbert.utils.utils import print_message
from colbert.modeling.tokenization import QueryTokenizer, DocTokenizer, tensorize_triples

from colbert.utils.runs import Run

random.seed(1234)

class LazyBatcher():
    def __init__(self, args, rank=0, nranks=1):
        self.bsize, self.accumsteps = args.bsize, args.accumsteps

        self.query_tokenizer = QueryTokenizer(args.query_maxlen, args.pretrained_tokenizer)
        self.doc_tokenizer = DocTokenizer(args.doc_maxlen, args.pretrained_tokenizer)
        self.tensorize_triples = partial(tensorize_triples, self.query_tokenizer, self.doc_tokenizer)
        self.position = 0

        # self.triples = self._load_triples(args.triples, rank, nranks)
        self.positive_pairs = self._load_positive_pairs(args.positives, rank, nranks)
        self.queries = self._load_queries(args.queries)
        self.collection = self._load_collection(args.collection)
        self.collection_keys = list(self.collection.keys())

    def _load_triples(self, path, rank, nranks):
        """
        NOTE: For distributed sampling, this isn't equivalent to perfectly uniform sampling.
        In particular, each subset is perfectly represented in every batch! However, since we never
        repeat passes over the data, we never repeat any particular triple, and the split across
        nodes is random (since the underlying file is pre-shuffled), there's no concern here.
        """
        print_message("#> Loading triples...")
        print_message(rank, nranks)
        triples = []

        with open(path) as f:
            for line_idx, line in enumerate(f):
                print(line)
                if line_idx % nranks == rank:
                    qid, pos, neg = ujson.loads(line)
                    triples.append((qid, pos, neg))

        return triples

    def _load_positive_pairs(self, path, rank, nranks):
        print_message("#> Loading positive pairs...")
        print_message(rank, nranks)
        positive_pairs = []

        with open(path) as f:
            for line_idx, line in enumerate(f):
                if line_idx % nranks == rank:
                    qid, pid = line.strip().split('\t')
                    positive_pairs.append((qid, pid))

        return positive_pairs

    def _load_queries(self, path):
        print_message("#> Loading queries...")

        queries = {}

        with open(path) as f:
            for line in f:
                qid, query = line.strip().split('\t')
                qid = int(qid)
                queries[qid] = query

        return queries

    def _load_collection(self, path):
        print_message("#> Loading collection...")

        collection = {}

        with open(path) as f:
            for _, line in enumerate(f):
                pid, passage = line.strip().split('\t')
                pid = int(pid)
                collection[pid] = passage

        return collection

    def __iter__(self):
        return self

    def __len__(self):
        return len(self.positive_pairs)

    def __next__(self):
        queries, positives, negatives = [], [], []
        
        p_augmented_query = random.uniform(0, 0.8)
        bsize = round(p_augmented_query * self.bsize)
        samples = random.sample(self.positive_pairs, bsize)
        # print_message(f"Probability for augment: {p_augmented_query}")
        # print_message(f"Augment nums: {self.bsize - bsize}")
        # get true positives and random negatives
        # print_message("Start getting true queries")
        for qid, pid_pos in samples:
            qid = int(qid)
            pid_pos = int(pid_pos)

            pid_neg = pid_pos
            while pid_neg == pid_pos:
                pid_neg = random.choice(self.collection_keys)
            
            query = self.queries[qid]
            pos = self.collection[pid_pos]
            neg = self.collection[pid_neg]

            queries.append(query)
            positives.append(pos)
            negatives.append(neg)
        
        # get augmented queries
        i = 0
        # print_message("Start getting augmented queries")
        while i < self.bsize - bsize:
        # for i in range(self.bsize - bsize):
            pid_pos = random.choice(self.collection_keys)
            pos = self.collection[pid_pos]
            sentences = sent_tokenize(pos)
            if len(sentences) < 3 or len(sentences) > 5: continue

            pid_neg = pid_pos
            while pid_neg == pid_pos:
                pid_neg = random.choice(self.collection_keys)

            neg = self.collection[pid_neg]

            num_sample = random.choice([1, 2])
            samples = random.sample(sentences, num_sample)
            # print(samples)
            query = " ".join(samples)
            queries.append(query)
            positives.append(pos)
            negatives.append(neg)
            i += 1
        # for query, pos, neg in zip(queries, positives, negatives):
        #     print_triples(query, pos, neg)
        # print_message(f"Queries length {len(queries)}")
        return self.collate(queries, positives, negatives)


    def collate(self, queries, positives, negatives):
        assert len(queries) == len(positives) == len(negatives) == self.bsize

        return self.tensorize_triples(queries, positives, negatives, self.bsize // self.accumsteps)

    def skip_to_batch(self, batch_idx, intended_batch_size):
        Run.warn(f'Skipping to batch #{batch_idx} (with intended_batch_size = {intended_batch_size}) for training.')
        self.position = intended_batch_size * batch_idx


# def print_triples(query, pos, neg):
#     print(f"Query: {query}")
#     print(f"Positive passage: {pos}")
#     print(f"Negative passage: {neg}")
#     print("-"*50)
# if __name__ == "__main__":
#     reader = LazyBatcher(args)

#     for batch_idx, BatchSteps in zip(range(0, 2), reader):
#         print_message(f"Batch {batch_idx}")
#         for queries, passages in BatchSteps:
#             pass
