import os
import h5py
import copy
import numpy as np
import random
import datetime
from itertools import compress
from collections import defaultdict
from sklearn.model_selection import train_test_split

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from geenuff.base.orm import Coordinate, Genome, Feature
from geenuff.base.helpers import full_db_path
from .numerify import CoordNumerifier


class ExportController(object):
    def __init__(self, db_path_in, data_dir, only_test_set=False):
        self.db_path_in = db_path_in
        self.only_test_set = only_test_set
        if not os.path.isdir(data_dir):
            os.makedirs(data_dir)
        elif os.listdir(data_dir):
            print('Output directory must be empty or not existing')
            exit()
        if self.only_test_set:
            print('Exporting all data into test_data.h5')
            self.h5_test = h5py.File(os.path.join(data_dir, 'test_data.h5'), 'w')
        else:
            print('Splitting data into training_data.h5 and validation_data.h5')
            self.h5_train = h5py.File(os.path.join(data_dir, 'training_data.h5'), 'w')
            self.h5_val = h5py.File(os.path.join(data_dir, 'validation_data.h5'), 'w')
        self._mk_session()

    def _mk_session(self):
        self.engine = create_engine(full_db_path(self.db_path_in), echo=False)
        self.session = sessionmaker(bind=self.engine)()

    @staticmethod
    def _split_sequences(flat_data, val_size):
        """Basically does the same as sklearn.model_selection.train_test_split except
        it does not always fill the test arrays with at least one element.
        Expects the arrays to be in the order: inputs, labels, label_masks
        """
        train_arrays, val_arrays = {}, {}
        for key in flat_data:
            train_arrays[key] = []
            val_arrays[key] = []

        for i in range(len(flat_data['inputs'])):
            if random.random() > val_size:
                for key in flat_data:
                    train_arrays[key].append(flat_data[key][i])
            else:
                for key in flat_data:
                    val_arrays[key].append(flat_data[key][i])
        return train_arrays, val_arrays

    def _save_data(self, h5_file, flat_data, chunk_size, n_y_cols):
        inputs = flat_data['inputs']
        labels = flat_data['labels']
        label_masks = flat_data['label_masks']
        # convert to numpy arrays

        # zero-pad each sequence to chunk_size
        # this is inefficient if there could be a batch with only sequences smaller than
        # chunk_size, but taking care of that introduces a lot of extra complexity
        n_seq = len(inputs)
        X = np.zeros((n_seq, chunk_size, 4), dtype=inputs[0].dtype)
        y = np.zeros((n_seq, chunk_size, n_y_cols), dtype=labels[0].dtype)
        sample_weights = np.zeros((n_seq, chunk_size), dtype=label_masks[0].dtype)
        for j in range(n_seq):
            sample_len = len(inputs[j])
            X[j, :sample_len, :] = inputs[j]
            y[j, :sample_len, :] = labels[j]
            sample_weights[j, :sample_len] = label_masks[j]
        err_samples = np.any(sample_weights == 0, axis=1)
        # just one entry per chunk
        if n_y_cols > 3:
            fully_intergenic_samples = np.all(y[:, :, 0] == 1, axis=1)
        else:
            fully_intergenic_samples = np.all(y[:, :, 0] == 0, axis=1)
        gc_contents = np.array(flat_data['gc_contents'], dtype=np.uint64)
        coord_lengths = np.array(flat_data['coord_lengths'], dtype=np.uint64)
        start_ends = np.array(flat_data['start_ends'], dtype=np.int64)
        # check if this is the first batch to save
        dset_keys = [
            'X', 'y', 'sample_weights', 'gc_contents', 'coord_lengths', 'err_samples',
            'fully_intergenic_samples', 'start_ends', 'species', 'seqids'
        ]
        if '/data/X' in h5_file:
            for dset_key in dset_keys:
                dset = h5_file['/data/' + dset_key]
                old_len = dset.shape[0]
                dset.resize(old_len + n_seq, axis=0)
        else:
            old_len = 0
            h5_file.create_dataset('/data/X',
                                   shape=(n_seq, chunk_size, 4),
                                   maxshape=(None, chunk_size, 4),
                                   chunks=(1, chunk_size, 4),
                                   dtype='float16',
                                   compression='lzf',
                                   shuffle=True)  # only for the compression
            h5_file.create_dataset('/data/y',
                                   shape=(n_seq, chunk_size, n_y_cols),
                                   maxshape=(None, chunk_size, n_y_cols),
                                   chunks=(1, chunk_size, n_y_cols),
                                   dtype='int8',
                                   compression='lzf',
                                   shuffle=True)
            h5_file.create_dataset('/data/sample_weights',
                                   shape=(n_seq, chunk_size),
                                   maxshape=(None, chunk_size),
                                   chunks=(1, chunk_size),
                                   dtype='int8',
                                   compression='lzf',
                                   shuffle=True)
            h5_file.create_dataset('/data/gc_contents',
                                   shape=(n_seq,),
                                   maxshape=(None,),
                                   dtype='uint64',
                                   compression='lzf')
            h5_file.create_dataset('/data/coord_lengths',
                                   shape=(n_seq,),
                                   maxshape=(None,),
                                   dtype='uint64',
                                   compression='lzf')
            h5_file.create_dataset('/data/err_samples',
                                   shape=(n_seq,),
                                   maxshape=(None,),
                                   dtype='bool',
                                   compression='lzf')
            h5_file.create_dataset('/data/fully_intergenic_samples',
                                   shape=(n_seq,),
                                   maxshape=(None,),
                                   dtype='bool',
                                   compression='lzf')
            h5_file.create_dataset('/data/species',
                                   shape=(n_seq,),
                                   maxshape=(None,),
                                   dtype='S25',
                                   compression='lzf')
            h5_file.create_dataset('/data/seqids',
                                   shape=(n_seq,),
                                   maxshape=(None,),
                                   dtype='S50',
                                   compression='lzf')
            h5_file.create_dataset('/data/start_ends',
                                   shape=(n_seq, 2),
                                   maxshape=(None, 2),
                                   dtype='int64',
                                   compression='lzf')
        # add new data
        dsets = [X, y, sample_weights, gc_contents, coord_lengths, err_samples,
                 fully_intergenic_samples, start_ends, flat_data['species'], flat_data['seqids']]
        for dset_key, data in zip(dset_keys, dsets):
            h5_file['/data/' + dset_key][old_len:] = data
        h5_file.flush()

    def _check_genome_names(self, *argv):
        for names in argv:
            if names:
                genome_ids = self.session.query(Genome.id).filter(Genome.species.in_(names)).all()
                if len(genome_ids) != len(names):
                    print('One or more of the given genome names can not be found in the database')
                    exit()

    def _get_coord_ids(self, genomes, exclude):
        coord_ids_with_features = self.session.query(Feature.coordinate_id).distinct()
        if genomes:
            print('Selecting the following genomes: {}'.format(genomes))
            all_coords = (self.session.query(Coordinate)
                         .join(Genome, Genome.id == Coordinate.genome_id)
                         .filter(Genome.species.in_(genomes))
                         .filter(Coordinate.id.in_(coord_ids_with_features))
                         .order_by(Coordinate.length.desc())
                         .all())
        else:
            if exclude:
                print('Selecting all genomes from {} except: {}'.format(self.db_path_in, exclude))
                all_coords = (self.session.query(Coordinate)
                             .join(Genome, Genome.id == Coordinate.genome_id)
                             .filter(Genome.species.notin_(exclude))
                             .filter(Coordinate.id.in_(coord_ids_with_features))
                             .order_by(Coordinate.length.desc())
                             .all())
            else:
                print('Selecting all genomes from {}'.format(self.db_path_in))
                all_coords = coord_ids_with_features.order_by(Coordinate.length.desc()).all()

        genome_coords = defaultdict(list)
        for c in all_coords:
            genome_coords[c.genome_id].append(c)
        return genome_coords

    def _split_coords_by_N90(self, genome_coords , val_size):
        """Splits the given coordinates in a train and val set. It does so by doing it individually for
        each the coordinates < N90 and >= N90 of each genome. It is inefficient to build this code
        on top of the output of self._get_coord_ids() but very convenient in terms of code structure."""
        def N90_index(coords):
            len_90_perc = int(sum([c.length for c in coords]) * 0.9)
            len_sum = 0
            for i, coord in enumerate(coords):
                len_sum += coord.length
                if len_sum >= len_90_perc:
                    return i

        train_coords, val_coords = [], []
        for coords in genome_coords.values():
            n90_idx = N90_index(coords) + 1
            for n90_split in [coords[:n90_idx], coords[n90_idx:]]:
                genome_train_coords, genome_val_coords = train_test_split(n90_split, test_size=val_size)
                train_coords += genome_train_coords
                val_coords += genome_val_coords
        return train_coords, val_coords

    def _add_data_attrs(self, genomes, exclude, one_hot_transitions, keep_errors):
        attrs = {
            'timestamp': str(datetime.datetime.now()),
            'genomes': ','.join(genomes),
            'exclude': ','.join(exclude),
            'one_hot_transitions': str(one_hot_transitions),
            'keep_errors': str(keep_errors),
        }
        for key, value in attrs.items():
            if self.only_test_set:
                self.h5_test.attrs[key] = value
            else:
                self.h5_train.attrs[key] = value
                self.h5_val.attrs[key] = value

    def _close_files(self):
        if self.only_test_set:
            self.h5_test.close()
        else:
            self.h5_train.close()
            self.h5_val.close()

    def _numerify_coord(self, coord, chunk_size, one_hot_transitions, keep_errors):
        list_in_list_out = ['inputs', 'labels', 'label_masks', 'start_ends']
        one_in_list_out = ['gc_contents', 'coord_lengths', 'species', 'seqids']
        # will pre-organize all data and metadata to have one entry per chunk in flat_data below
        flat_data = {}
        for key in list_in_list_out + one_in_list_out:
            flat_data[key] = []

        n_masked_bases, n_intergenic_bases = 0, 0
        for is_plus_strand in [True, False]:
            numerifier = CoordNumerifier(self.session, coord, is_plus_strand, chunk_size, one_hot_transitions)
            coord_data = numerifier.numerify()
            # keep track of variables
            n_masked_bases += sum(
                [np.count_nonzero(m == 0) for m in coord_data['label_masks']])
            if one_hot_transitions:
                n_intergenic_bases += sum([np.count_nonzero(l[:, 0] == 1) for l in coord_data['labels']])
            else:
                n_intergenic_bases += sum(
                    [np.count_nonzero(np.all(l == 0, axis=1)) for l in coord_data['labels']])
            # filter out sequences that are completely masked as error
            if not keep_errors:
                valid_data = [s.any() for s in coord_data['label_masks']]
                for key in list_in_list_out:
                    coord_data[key] = list(compress(coord_data[key], valid_data))
            # add data
            for key in list_in_list_out:
                flat_data[key] += coord_data[key]
            for key in one_in_list_out:
                flat_data[key] += [coord_data[key]] * len(coord_data['inputs'])
        masked_bases_percent = n_masked_bases / (coord.length * 2) * 100
        intergenic_bases_percent = n_intergenic_bases / (coord.length * 2) * 100
        return flat_data, coord, masked_bases_percent, intergenic_bases_percent

    def export(self, chunk_size, genomes, exclude, val_size, one_hot_transitions, split_coordinates, keep_errors):
        self._check_genome_names(genomes, exclude)
        genome_coords = self._get_coord_ids(genomes, exclude)
        n_coords = sum([len(coords) for genome_id, coords in genome_coords.items()])
        print('\n{} coordinates chosen to numerify'.format(n_coords))
        if split_coordinates:
            train_coords, val_coords = self._split_coords_by_N90(genome_coords, val_size)

        n_coords_done = 1
        n_y_cols = 7 if one_hot_transitions else 4

        for coords in genome_coords.values():
            for coord in coords:
                numerify_outputs = self._numerify_coord(coord, chunk_size, one_hot_transitions, keep_errors)
                flat_data, coord, masked_bases_percent, intergenic_bases_percent = numerify_outputs
                if split_coordinates or self.only_test_set:
                    if split_coordinates:
                        if coord in train_coords:
                            self._save_data(self.h5_train, flat_data, chunk_size, n_y_cols)
                            assigned_set = 'train'
                        else:
                            self._save_data(self.h5_val, flat_data, chunk_size, n_y_cols)
                            assigned_set = 'val'
                    elif self.only_test_set:
                        self._save_data(self.h5_test, flat_data, chunk_size, n_y_cols)
                        assigned_set = 'test'
                    print(('{}/{} Numerified {} of {} with {} features in {} chunks '
                           'with an error rate of {:.2f}%, and intergenic rate of {:.2f}% ({})').format(
                               n_coords_done, n_coords,  coord, coord.genome.species,
                               len(coord.features), len(flat_data['inputs']), masked_bases_percent,
                               intergenic_bases_percent, assigned_set))
                else:
                    # split sequences
                    train_data, val_data = self._split_sequences(flat_data, val_size=val_size)
                    if train_data['inputs']:
                        self._save_data(self.h5_train, train_data, chunk_size, n_y_cols)
                    if val_data['inputs']:
                        self._save_data(self.h5_val, val_data, chunk_size, n_y_cols)
                    print(('{}/{} Numerified {} of {} with {} features in {} chunks '
                           '(train: {}, test: {}) with an error rate of {:.2f}% and an '
                           'intergenic rate of {:.2f}%').format(
                               n_coords_done, n_coords, coord, coord.genome.species,
                               len(coord.features), len(flat_data['inputs']), len(train_data['inputs']),
                               len(val_data['inputs']), masked_bases_percent, intergenic_bases_percent))
                n_coords_done += 1

        self._add_data_attrs(genomes, exclude, one_hot_transitions, keep_errors)
        self._close_files()
