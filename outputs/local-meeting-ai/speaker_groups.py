"""Reconcile acoustic clusters across windows before assigning enrolled names."""
import numpy as np


def unit(v):
    v=np.asarray(v,dtype=np.float32)
    return v/max(float(np.linalg.norm(v)),1e-8)


def reconcile(entries, threshold=0.80):
    # Complete-link matching prevents chains of weak similarities merging people.
    groups=[]
    for entry in sorted(entries,key=lambda x:-x['seconds']):
        if entry['vector'] is None or entry['seconds']<2:continue
        candidates=[]
        for i,group in enumerate(groups):
            overlaps=False
            for member in group:
                overlap=sum(max(0,min(b,d)-max(a,c)) for a,b in entry['intervals'] for c,d in member['intervals'])
                shorter=min(sum(b-a for a,b in entry['intervals']),sum(b-a for a,b in member['intervals']))
                if overlap>min(.5,.02*shorter):overlaps=True
            score=min(float(np.dot(unit(entry['vector']),unit(m['vector']))) for m in group)
            if not overlaps and score>=threshold:candidates.append((score,i))
        candidates.sort(reverse=True)
        if candidates and (len(candidates)==1 or candidates[0][0]-candidates[1][0]>=.10):
            groups[candidates[0][1]].append(entry)
        else:groups.append([entry])
    return sorted(groups,key=lambda g:min(a for m in g for a,b in m['intervals']))


def corroborated_name(group,people):
    # A domain shift (headset enrollment vs room audio) can lower absolute
    # scores. Require repeated long samples and a large lead over every rival.
    votes=[]
    for member in group:
        if member['seconds']<5:continue
        scores=sorted([(float(np.dot(unit(member['vector']),unit(p['embedding']))),p['id']) for p in people],reverse=True)
        if len(scores)<2 or scores[0][0]<.55 or scores[0][0]-scores[1][0]<.20:return None
        votes.append(scores[0][1])
    if len(votes)<2 or len(set(votes))!=1 or sum(m['seconds'] for m in group)<20:return None
    return next(p for p in people if p['id']==votes[0])
