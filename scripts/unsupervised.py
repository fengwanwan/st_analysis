#! /usr/bin/env python
"""
A script that does un-supervised
classification on single cell data (Mainly used for Spatial Transcriptomics)
It takes a list of data frames as input and outputs :

 - the normalized counts as a data frame for all the datasets 
 - a scatter plot with the predicted classes for each spot 
 - a file with the predicted classes for each spot and the spot coordinates

The spots in the output file will have the index of the dataset
appended. For instance if two datasets are given the indexes will
be (1 and 2). 

The user can select what clustering algorithm to use
and what dimensionality reduction technique to use. 

The user can optionally give a list of images
and image alignments to plot the predicted classes
on top of the image. Then one image for each dataset
will be generated.

@Author Jose Fernandez Navarro <jose.fernandez.navarro@scilifelab.se>
"""
import argparse
import sys
import os
import numpy as np
import pandas as pd
from sklearn.manifold import TSNE
from sklearn.decomposition import PCA, FastICA, SparsePCA
#from sklearn.cluster import DBSCAN
from sklearn.cluster import KMeans
from sklearn.cluster import AgglomerativeClustering
#from sklearn.preprocessing import scale
from stanalysis.visualization import scatter_plot
from stanalysis.normalization import computeSizeFactors
from stanalysis.alignment import parseAlignmentMatrix

MIN_GENES_SPOT_EXP = 0.1
MIN_GENES_SPOT_VAR = 0.2
MIN_FEATURES_GENE = 10
MIN_EXPRESION = 2
DIMENSIONS = 2

def main(counts_table_files, 
         normalization, 
         num_clusters, 
         clustering_algorithm, 
         dimensionality_algorithm,
         outdir,
         alignment_files, 
         image_files):

    if len(counts_table_files) == 0 or any([not os.path.isfile(f) for f in counts_table_files]):
        sys.stderr.write("Error, input file/s not present or invalid format\n")
        sys.exit(1)
            
    if outdir is None: 
        outdir = os.getcwd()
       
    # Spots are rows and genes are columns
    index_to_spots = [[] for ele in xrange(len(counts_table_files))]
    counts = pd.DataFrame()
    for i,counts_file in enumerate(counts_table_files):
        new_counts = pd.read_table(counts_file, sep="\t", header=0, index_col=0)
        new_spots = ["{0}_{1}".format(i, spot) for spot in new_counts.index]
        new_counts.index = new_spots
        counts = counts.append(new_counts)
        index_to_spots[i].append(new_spots)
    counts.fillna(0.0, inplace=True)
    
    # How many spots do we keep based on the number of genes expressed?
    min_genes_spot_exp = round((counts != 0).sum(axis=1).quantile(MIN_GENES_SPOT_EXP))
    print "Number of expressed genes a spot must have to be kept " \
    "(1% of total expressed genes) {}".format(min_genes_spot_exp)
    
    # Remove noisy spots  
    counts = counts[(counts != 0).sum(axis=1) >= min_genes_spot_exp]
    # Spots are columns and genes are rows
    counts = counts.transpose()
    # Remove noisy genes
    counts = counts[(counts >= MIN_EXPRESION).sum(axis=1) >= MIN_FEATURES_GENE]
    
    # Normalization
    if normalization in "DESeq":
        size_factors = computeSizeFactors(counts, function=np.median)
        norm_counts = counts.div(size_factors) 
    elif normalization in "TPM":
        #    feature.sums = apply(exp.values, 2, sum)
        #    norm.counts = (t(t(exp.values) / feature.sums)*1e6) + 1
        spots_sum = counts.sum(axis=1)
        norm_counts = ((counts.transpose().div(spots_sum)) * 1e6).transpose()
    elif normalization in "RAW":
        norm_counts = counts
    else:
        sys.stderr.write("Error, incorrect normalization method\n")
        sys.exit(1)
    
    # Scale spots (columns) against the mean and variance
    #norm_counts = pd.DataFrame(data=scale(norm_counts, axis=1, with_mean=True, with_std=True), 
    #                           index=norm_counts.index, columns=norm_counts.columns)
    
    # Keep only the genes with higher over-all variance
    # NOTE: this could be done to keep the genes with the highest counts
    min_genes_spot_var = norm_counts.var(axis=1).quantile(MIN_GENES_SPOT_VAR)
    print "Min variance a gene must have over all spot " \
    "to be kept ({0}% of total) {1}".format(MIN_GENES_SPOT_VAR,min_genes_spot_var)
    norm_counts = norm_counts[norm_counts.var(axis=1) >= min_genes_spot_var]
    
    # Spots as rows and genes as columns
    norm_counts = norm_counts.transpose()
    # Write normalized and filtered counts to a file
    norm_counts.to_csv(os.path.join(outdir, "normalized_counts.tsv"), sep="\t")
              
    if "tSNE" in dimensionality_algorithm:
        # method = barnes_hut or exact(slower)
        # init = pca or random
        # random_state = None or number
        # metric = euclidean or any other
        # n_components = 2 is default
        decomp_model = TSNE(n_components=DIMENSIONS, random_state=None, perplexity=5,
                            early_exaggeration=4.0, learning_rate=1000, n_iter=1000,
                            n_iter_without_progress=30, metric="euclidean", init="pca",
                            method="barnes_hut", angle=0.0)
    elif "PCA" in dimensionality_algorithm:
        # n_components = None, number of mle to estimate optimal
        decomp_model = PCA(n_components=DIMENSIONS, whiten=True, copy=True)
    elif "ICA" in dimensionality_algorithm:
        decomp_model = FastICA(n_components=DIMENSIONS, 
                               algorithm='parallel', whiten=True,
                               fun='logcosh', w_init=None, random_state=None)
    elif "SPCA" in dimensionality_algorithm:
        decomp_model = SparsePCA(n_components=DIMENSIONS, alpha=1)
    else:
        sys.stderr.write("Error, incorrect dimensionality reduction method\n")
        sys.exit(1)
    
    # Use log2 counts if we do not center the data
    reduced_data = decomp_model.fit_transform(np.log2(norm_counts + 1))
    
    # Do clustering of the dimensionality reduced coordinates
    if "KMeans" in clustering_algorithm:
        clustering = KMeans(init='k-means++', n_clusters=num_clusters, n_init=10)    
    elif "Hierarchical" in clustering_algorithm:
        clustering = AgglomerativeClustering(n_clusters=num_clusters, 
                                             affinity='euclidean',
                                             n_components=None, linkage='ward') 
    else:
        sys.stderr.write("Error, incorrect clustering method\n")
        sys.exit(1)

    labels = clustering.fit_predict(reduced_data)
    if 0 in labels: labels = labels + 1
    
    # Plot the clustered spots with the class color
    scatter_plot(x_points=reduced_data[:,0], 
                 y_points=reduced_data[:,1], 
                 colors=labels, 
                 output=os.path.join(outdir,"computed_classes.png"), 
                 alignment=None, 
                 cmap=None, 
                 title='Computed classes', 
                 xlabel='X', 
                 ylabel='Y',
                 image=None, 
                 alpha=1.0, 
                 size=80)
    
    # Write the spots and their classes to a file
    assert(len(labels) == len(norm_counts.index))
    # First get the spots coordinates
    x_points_index = [[] for ele in xrange(len(counts_table_files))]
    y_points_index = [[] for ele in xrange(len(counts_table_files))]
    labels_index = [[] for ele in xrange(len(counts_table_files))]
    # Write the coordinates and the label/class the belong to
    with open(os.path.join(outdir, "computed_classes.txt"), "w") as filehandler:
        for i,bc in enumerate(norm_counts.index):
            # bc is XxY_i
            tokens = bc.split("x")
            assert(len(tokens) == 2)
            y = int(tokens[1])
            x = int(tokens[0].split("_")[1])
            index = int(tokens[0].split("_")[0])
            x_points_index[index].append(x)
            y_points_index[index].append(y)
            labels_index[index].append(labels[i])
            filehandler.write("{0}\t{1}\n".format(labels[i], bc))
    
    for i,image in enumerate(image_files) if image_files else []:
        if image is not None and os.path.isfile(image):
            alignment_file = alignment_files[i] if len(alignment_files) >= i else None
            # alignment_matrix will be identity if alignment file is None
            alignment_matrix = parseAlignmentMatrix(alignment_file)            
            scatter_plot(x_points=x_points_index[i], 
                         y_points=y_points_index[i], 
                         colors=labels_index[i], 
                         output=os.path.join(outdir,"computed_classes_tissue_{}.png".format(i)), 
                         alignment=alignment_matrix, 
                         cmap=None, 
                         title='Computed classes tissue', 
                         xlabel='X', 
                         ylabel='Y',
                         image=image, 
                         alpha=1.0, 
                         size=60)
             
                                
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts-table-files", required=True, nargs='+', type=str,
                        help="One or more tables with gene counts per feature/spot (genes as columns)")
    parser.add_argument("--normalization", default="DESeq", metavar="[STR]", 
                        type=str, choices=["RAW", "DESeq", "TPM"],
                        help="Normalize the counts using (RAW - DESeq - TPM) (default: %(default)s)")
    parser.add_argument("--num-clusters", default=3, metavar="[INT]", type=int, choices=range(2, 10),
                        help="If given the number of clusters will be adjusted. " \
                        "Otherwise they will be pre-computed (default: %(default)s)")
    parser.add_argument("--clustering-algorithm", default="KMeans", metavar="[STR]", 
                        type=str, choices=["Hierarchical", "KMeans"],
                        help="What clustering algorithm to use after the dimensionality reduction " \
                        "(Hierarchical - KMeans) (default: %(default)s)")
    parser.add_argument("--dimensionality-algorithm", default="ICA", metavar="[STR]", 
                        type=str, choices=["tSNE", "PCA", "ICA", "SPCA"],
                        help="What dimensionality reduction algorithm to use " \
                        "(tSNE - PCA - ICA - SPCA) (default: %(default)s)")
    parser.add_argument("--alignment-files", default=None, nargs='+', type=str,
                        help="One of moref files containing the alignment maxtris for the images " \
                        "(array coordinates to pixel coordinates) as a 3x3 matrix")
    parser.add_argument("--image-files", default=None, nargs='+', type=str,
                        help="When given the data will plotted on top of the image, " \
                        "if the alignment matrix is given the data will be aligned.\n" \
                        "It can be one ore more, ideally one for each input dataset.")
    parser.add_argument("--outdir", default=None, help="Path to output dir")
    args = parser.parse_args()
    main(args.counts_table_files, args.normalization, int(args.num_clusters), 
         args.clustering_algorithm, args.dimensionality_algorithm,
         args.outdir, args.alignment_files, args.image_files)

