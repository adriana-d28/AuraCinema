# `movies_catalogue.csv`: licence and source

`movies_catalogue.csv` is the only file in this folder that is versioned. The
other files (training/test ratings and the dataset manifest) are generated
locally by `ml/src/prepare_data.py` and are not committed.

## What the file is

It is the AuraCinema movie catalogue: the 5,068 movies selected by
`ml/src/prepare_data.py`. It has one row per movie with the columns `movieId`,
`title`, `genres`, `imdbId` and `tmdbId`.

It is a **transformation of the MovieLens 32M dataset (ml-32m)**, built only
from its `movies.csv` and `links.csv` files. No data in it was obtained from
the TMDB API: the TMDB and IMDb identifiers come from MovieLens `links.csv`.

The backend loads it into PostgreSQL with `backend/scripts/seed_movies.py`.

## Licence

This file is redistributed under the same licence conditions as the MovieLens
dataset, as that licence requires. The MovieLens usage licence is reproduced
below, verbatim from the dataset's `README.txt`:

> Neither the University of Minnesota nor any of the researchers involved can guarantee the correctness of the data, its suitability for any particular purpose, or the validity of results based on the use of the data set. The data set may be used for any research purposes under the following conditions:
>
> * The user may not state or imply any endorsement from the University of Minnesota or the GroupLens Research Group.
> * The user must acknowledge the use of the data set in publications resulting from the use of the data set (see below for citation information).
> * The user may redistribute the data set, including transformations, so long as it is distributed under these same license conditions.
> * The user may not use this information for any commercial or revenue-bearing purposes without first obtaining permission from a faculty member of the GroupLens Research Project at the University of Minnesota.
> * The executable software scripts are provided "as is" without warranty of any kind, either expressed or implied, including, but not limited to, the implied warranties of merchantability and fitness for a particular purpose. The entire risk as to the quality and performance of them is with you. Should the program prove defective, you assume the cost of all necessary servicing, repair or correction.
>
> In no event shall the University of Minnesota, its affiliates or employees be liable to you for any damages arising out of the use or inability to use these programs (including but not limited to loss of data or data being rendered inaccurate).
>
> If you have any further questions or comments, please email <grouplens-info@umn.edu>

AuraCinema is a non-commercial academic project. It is not endorsed by the
University of Minnesota or the GroupLens Research Group.

## Citation

> F. Maxwell Harper and Joseph A. Konstan. 2015. The MovieLens Datasets: History and Context. ACM Transactions on Interactive Intelligent Systems (TiiS) 5, 4: 19:1–19:19. <https://doi.org/10.1145/2827872>

The original dataset is available at <https://grouplens.org/datasets/movielens/>.
