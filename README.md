# Helixer
Gene calling with Deep Neural Networks.

## Disclaimer
This software is very much beta and probably not stable enough to build on (yet).

## Goal
Setup and train models for _de novo_ prediction of gene structure.
That is, to perform "gene calling" and identify
which base pairs in a genome belong to the UTR/CDS/Intron of genes. 
Train one model for a wide variety of genomes.

## Install 

### Get the code
First, download and checkout the latest release
```shell script
# from a directory of your choice
git clone https://github.com/weberlab-hhu/Helixer.git
cd Helixer
# git checkout dev # v0.2.0
```

### System dependencies

#### Python 3.6 or later

#### Python development libraries
Ubuntu (& co.)
```shell script
sudo apt install python3-dev
```
Fedora (& co.)
```shell script
sudo dnf install python3-devel
```

### Virtualenv (optional)
We recommend installing all the python packages in a
virtual environment: https://docs.python-guide.org/dev/virtualenvs/

For example, create and activate an environment called 'env': 
```shell script
python3 -m venv env
source env/bin/activate
```
The steps below assume you are working in the same environment.

### GPU requirements (optional, but highly recommended for realistically sized datasets)
And to run on a GPU (highly recommended for realistically sized datasets),
everything for tensorflow-gpu is required, 
see: https://www.tensorflow.org/install/gpu


The following has been most recently tested.

python packages:
* tensorflow-gpu==2.7.0

system packages:
* cuda-11-2
* libcudnn8
* libcudnn8-dev
* nvidia-driver-495

A GPU with 11GB Memory (e.g. GTX 1080 Ti) can run the largest 
configurations described below, for smaller GPUs you might
have to reduce the network or batch size. 
  
### Most python dependencies 
```shell script
pip install -r requirements.txt
```

### Helixer itself

```shell script
# from the Helixer directory
pip install .  # or `pip install -e .`, if you will be changing the code
```

## Example
We set up a working example with a limited amount of data. 
For this, we will utilize the GeenuFF database in 
located at `example/three_algae.sqlite3` to generate a training, 
validation and testing dataset and then use those to first train a model 
and then to make gene predictions with Helixer.

### Generating training-ready data

#### Pre-processing w/ GeenuFF
>Note: you will be able to skip working with GeenuFF if
> only wish to predict, and not train. See instead the
> --direct-fasta-to-h5-path parameter of Helixer/export.py

First we will need to pre-process the data (Fasta & GFF3 files)
using GeenuFF. This provides a more biologically-realistic
representation of gene structures, and, most importantly
right now, provides identification and masking of invalid
gene structures from the gff file (e.g. those that don't
have _any_ UTR between coding and intergenic or those that
have overlapping exons within one transcript). 

See the GeenuFF repository for more information.

For now we can just run the provided example script to
download and pre-process some algae data.

```shell script
cd <your/path/to>/GeenuFF
bash example.sh
# store full path in a variable for later usage
data_at=`readlink -f three_algae`
cd <your/path/to/Helixer>
```
This downloads and pre-processes data for the species
(Chlamydomonas_reinhardtii,  Cyanidioschyzon_merolae, and  Ostreococcus_lucimarinus)
as you can see with `ls $data_at`
#### numeric encoding of data
To actually train (or predict) we will need to encode the
data numerically (e.g. as 1s and 0s). 

```shell script
mkdir -p example/h5s
for species in `ls $data_at`
do
  mkdir example/h5s/$species
  python export.py --input-db-path $data_at/$species/output/$species.sqlite3 \
    --output-path example/h5s/$species/test_data.h5
done
```
To create the simples working example, we will use Chlamydomonas_reinhardtii 
for training and Cyanidioschyzon_merolae for validation (normally you
would merge multiple species for each) and use Ostreococcus_lucimarinus for
testing / predicting / etc.

```shell script
# The training script requires two files in one folder named
# training_data.h5 and validation_data.h5
#
# while we would need to merge multiple datasets to create our
# training_data.h5 and validation_data.h5 normally, for this as-simple-
# as-possible example we will point to one species each with symlinks
mkdir example/train
cd example/train/
# set training data 
ln -s ../h5s/Chlamydomonas_reinhardtii/test_data.h5 training_data.h5
# and validation
ln -s ../h5s/Cyanidioschyzon_merolae/test_data.h5 validation_data.h5
cd ../..
```

We should now have the following files in `example/`. 
Note that the test data was not split into a training 
and validation set due to the `--only-test-set` option: 
```
example
├── h5s
│   ├── Chlamydomonas_reinhardtii
│   │   └── test_data.h5
│   ├── Cyanidioschyzon_merolae
│   │   └── test_data.h5
│   └── Ostreococcus_lucimarinus
│       └── test_data.h5
└── train
    ├── training_data.h5 -> ../h5s/Chlamydomonas_reinhardtii/test_data.h5
    └── validation_data.h5 -> ../h5s/Cyanidioschyzon_merolae/test_data.h5
```

### Model training
Now we use the datasets in `example/train/` to train a model with our 
LSTM architeture for 5 epochs and save the best iteration 
(according to the Genic F1 on the validation dataset) to 
`example/best_helixer_model.h5`. 

```shell script
python3 helixer/prediction/DanQModel.py --data-dir example/train/ --save-model-path example/best_helixer_model.h5 --epochs 5 
```

The rest of this example will continue with the model example/best_helixer_model.h5 produced above. 

#### Full size aside
The current 'full size' architecture that has been performing well
in hyper optimization runs is:

```shell script
# the indicated batch size and val-test-batch size have been chosen to work on a 2080ti with 11GB RAM
# and should be set as large as the graphics card will allow. 
python helixer/prediction/DanQModel.py -v --pool-size 9 --batch-size 50 --val-test-batch-size 100 \
  --class-weights "[0.7, 1.6, 1.2, 1.2]" --transition-weights "[1, 12, 3, 1, 12, 3]" --predict-phase \
  --lstm-layers 3 --cnn-layers 4 --units 128 --filter-depth 96 --kernel-size 10 \
  --data-dir example/train/ --save-model-path example/fullsize_helixer_model.h5
```

But make sure you have a full size dataset to go with that model, if you're going to train it.

### Model evaluation
We can now use the mini model trained above to produce predictions for our test dataset. 
WARNING: Generating predictions can produce very large files as 
we save every individual softmax value in 32 bit floating point format. 
For this very small genome the predictions require 524MB of disk space. 
```shell script
python helixer/prediction/DanQModel.py --load-model-path example/best_helixer_model.h5 \
  --test-data example/h5s/Ostreococcus_lucimarinus/test_data.h5 \
  --prediction-output-path example/Ostreococcus_lucimarinus_predictions.h5
```

Or we can directly evaluate the predictive performance of our model. It is necessary to generate a test data file per species to get results for just that species.

```shell script
python helixer/prediction/DanQModel.py --load-model-path example/best_helixer_model.h5 \
  --test-data example/h5s/Ostreococcus_lucimarinus/test_data.h5 --eval
```

The last command can be sped up with a higher batch size and should give us the same break down that is performed 
during after a training epoch, but on the test data:

```
+confusion_matrix------+----------+-----------+-------------+
|            | ig_pred | utr_pred | exon_pred | intron_pred |
+------------+---------+----------+-----------+-------------+
| ig_ref     | 1297055 | 151436   | 692534    | 188423      |
| utr_ref    | 159457  | 32821    | 99856     | 16345       |
| exon_ref   | 5014284 | 2002047  | 2001614   | 134915      |
| intron_ref | 199752  | 62334    | 89647     | 9550        |
+------------+---------+----------+-----------+-------------+

+normalized_confusion_matrix------+-----------+-------------+
|            | ig_pred | utr_pred | exon_pred | intron_pred |
+------------+---------+----------+-----------+-------------+
| ig_ref     | 0.5568  | 0.065    | 0.2973    | 0.0809      |
| utr_ref    | 0.5169  | 0.1064   | 0.3237    | 0.053       |
| exon_ref   | 0.5478  | 0.2187   | 0.2187    | 0.0147      |
| intron_ref | 0.5529  | 0.1725   | 0.2481    | 0.0264      |
+------------+---------+----------+-----------+-------------+

+F1_summary--+---------+-----------+--------+----------+
|            | norm. H | Precision | Recall | F1-Score |
+------------+---------+-----------+--------+----------+
| ig         |         | 0.1944    | 0.5568 | 0.2882   |
| utr        |         | 0.0146    | 0.1064 | 0.0257   |
| exon       |         | 0.6941    | 0.2187 | 0.3326   |
| intron     |         | 0.0273    | 0.0264 | 0.0269   |
|            |         |           |        |          |
| legacy_cds |         | 0.6916    | 0.2350 | 0.3508   |
| sub_genic  |         | 0.6221    | 0.2114 | 0.3156   |
| genic      |         | 0.3729    | 0.2081 | 0.2671   |
+------------+---------+-----------+--------+----------+
Total acc: 0.2749

metrics calculation took: 0.08 minutes
```

In the demo run above (yours may vary) the model predicted
perhaps better than random, but poorly, it practically
need more and more varied (from different species) data
to train it (this result is for the small model example).


### Using trained models
> WARNING: to use the pre-trained models you will need the published
> version of the code! Run `git checkout v0.2.0` and follow the instructions
> there in. As soon as pre-trained phase-containing models are generally 
> available and evaluated, this section will be updated.

#### Citation

Felix Stiehler, Marvin Steinborn, Stephan Scholz, Daniela Dey, Andreas P M Weber, Alisandra K Denton, 
Helixer: Cross-species gene annotation of large eukaryotic genomes using deep learning, Bioinformatics, , btaa1044, 
https://doi.org/10.1093/bioinformatics/btaa1044
